"""tests/test_pr5_registered_runtime_device_canonical.py
=========================================================
Tests for PR-5: Standardize ``RegisteredRuntimeDevice`` as the **sole
canonical external single-device read contract**.

Coverage:
  1. UDM → ``RegisteredRuntimeDevice`` projection (all six information domains).
  2. DeviceRegistry record → ``RegisteredRuntimeDevice`` projection.
  3. Android-originated state → ``RegisteredRuntimeDevice`` projection.
  4. Router-derived runtime state → ``RegisteredRuntimeDevice`` projection.
  5. Agent-backed / DeviceAgentManager → ``RegisteredRuntimeDevice`` projection.
  6. Serialisation stability and graceful partial-field handling.
  7. Canonical authority — ``from_device_agent_manager_record`` re-exported
     from ``contracts`` and ``core.unified``.
  8. All six information domains are present and correctly populated.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _udm_device(**kw: Any) -> MagicMock:
    """Mock ``core.unified.models.UnifiedDevice``."""
    m = MagicMock()
    m.device_id = kw.get("device_id", "udm_001")
    m.device_name = kw.get("device_name", "UDM Phone")
    m.device_type = kw.get("device_type", "android")
    m.status = kw.get("status", "online")
    m.capabilities = kw.get("capabilities", ["screen", "camera"])
    m.metadata = kw.get("metadata", {"source": "udm"})
    m.last_heartbeat = kw.get("last_heartbeat", None)
    m.is_online.return_value = kw.get("status", "online") == "online"
    return m


def _registry_device(**kw: Any) -> MagicMock:
    """Mock ``core.schemas.device.DeviceModel``."""
    m = MagicMock()
    m.device_id = kw.get("device_id", "reg_001")
    m.name = kw.get("name", "Registry Desktop")
    raw_type = MagicMock()
    raw_type.value = kw.get("device_type", "windows")
    m.device_type = raw_type
    raw_status = MagicMock()
    raw_status.value = kw.get("status", "online")
    m.status = raw_status
    cap = MagicMock()
    cap.name = "screen"
    m.capabilities = kw.get("capabilities", [cap])
    m.last_seen = kw.get("last_seen", time.time())
    m.last_heartbeat = kw.get("last_heartbeat", None)
    m.groups = kw.get("groups", ["office"])
    m.tags = kw.get("tags", ["prod"])
    m.metadata = kw.get("metadata", {})
    return m


def _router_device(**kw: Any) -> MagicMock:
    """Mock ``galaxy_gateway.device_router.Device``."""
    m = MagicMock()
    m.device_id = kw.get("device_id", "router_001")
    m.device_name = kw.get("device_name", "Router Laptop")
    m.device_type = kw.get("device_type", "linux")
    m.capabilities = kw.get("capabilities", ["screen", "keyboard"])
    m.websocket = kw.get("websocket", MagicMock())
    m.metadata = kw.get("metadata", {})
    return m


def _agent_device_info(**kw: Any) -> MagicMock:
    """Mock ``core.device_agent_manager.DeviceInfo``."""
    m = MagicMock()
    m.device_id = kw.get("device_id", "agent_001")
    m.device_name = kw.get("device_name", "Agent IoT Device")
    # device_type as enum-like with .value
    device_type_mock = MagicMock()
    device_type_mock.value = kw.get("device_type", "iot")
    m.device_type = kw.get("device_type_obj", device_type_mock)
    # status as enum-like with .value
    status_mock = MagicMock()
    status_mock.value = kw.get("status", "online")
    m.status = kw.get("status_obj", status_mock)
    # capabilities as enum-like with .value
    cap_mock = MagicMock()
    cap_mock.value = "gps"
    m.capabilities = kw.get("capabilities", [cap_mock])
    m.metadata = kw.get("metadata", {"region": "us-west"})
    m.last_heartbeat = kw.get("last_heartbeat", None)
    m.registered_at = kw.get("registered_at", None)
    return m


def _android_payload(**kw: Any) -> dict:
    return {
        "device_id": kw.get("device_id", "android_001"),
        "name": kw.get("name", "Pixel 9"),
        "model": kw.get("model", "Pixel 9"),
        "os_version": kw.get("os_version", "15"),
        "sdk_version": kw.get("sdk_version", 35),
        "capabilities": kw.get("capabilities", ["screen", "camera"]),
        "app_version": kw.get("app_version", "3.2.0"),
        "device_type": kw.get("device_type", "android_phone"),
    }


# ---------------------------------------------------------------------------
# 1. UDM → RegisteredRuntimeDevice
# ---------------------------------------------------------------------------

class TestUdmProjection:
    """UDM device projects correctly into all six canonical information domains."""

    def test_identity_domain(self):
        from contracts.registered_runtime_device import from_udm_device
        m = _udm_device(device_id="udm_id_01", device_name="UDM Identity Phone")
        c = from_udm_device(m)
        # domain 1: identity
        assert c.device_id == "udm_id_01"
        assert c.device_name == "UDM Identity Phone"

    def test_registration_domain(self):
        from contracts.registered_runtime_device import from_udm_device, RuntimeDevicePlatform
        m = _udm_device(device_type="android")
        c = from_udm_device(m)
        # domain 2: registration
        assert c.platform in (RuntimeDevicePlatform.ANDROID, "android")
        assert c.device_type == "android"

    def test_runtime_presence_domain_online(self):
        from contracts.registered_runtime_device import from_udm_device, RuntimeDeviceStatus
        m = _udm_device(status="online")
        c = from_udm_device(m)
        # domain 3: runtime presence
        assert c.online is True
        assert c.status in (RuntimeDeviceStatus.ONLINE, "online")

    def test_runtime_presence_domain_offline(self):
        from contracts.registered_runtime_device import from_udm_device
        m = _udm_device(status="offline")
        c = from_udm_device(m)
        assert c.online is False

    def test_runtime_presence_last_seen_from_datetime(self):
        from contracts.registered_runtime_device import from_udm_device
        lh = datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc)
        m = _udm_device(last_heartbeat=lh)
        c = from_udm_device(m)
        # domain 3: last_seen populated
        assert c.last_seen is not None
        assert isinstance(c.last_seen, float)

    def test_capability_domain(self):
        from contracts.registered_runtime_device import from_udm_device
        m = _udm_device(capabilities=["screen", "camera", "gps"])
        c = from_udm_device(m)
        # domain 4: capability
        assert "screen" in c.capabilities.capabilities
        assert "gps" in c.capabilities.capabilities

    def test_topology_hint_runtime_enabled_when_online(self):
        from contracts.registered_runtime_device import from_udm_device
        m = _udm_device(status="online")
        c = from_udm_device(m)
        # domain 6: topology / runtime hints
        assert c.autonomy.runtime_enabled is True

    def test_metadata_preserved(self):
        from contracts.registered_runtime_device import from_udm_device
        m = _udm_device(metadata={"extra": "udm_meta"})
        c = from_udm_device(m)
        assert c.metadata.get("extra") == "udm_meta"

    def test_missing_optional_fields_graceful(self):
        from contracts.registered_runtime_device import from_udm_device
        m = MagicMock()
        m.device_id = "udm_sparse"
        m.device_name = None
        m.device_type = None
        m.status = None
        m.capabilities = None
        m.metadata = None
        m.last_heartbeat = None
        c = from_udm_device(m)
        assert c.device_id == "udm_sparse"
        assert isinstance(c.capabilities.capabilities, list)

    def test_produces_valid_contract_instance(self):
        from contracts.registered_runtime_device import from_udm_device, RegisteredRuntimeDevice
        c = from_udm_device(_udm_device())
        assert isinstance(c, RegisteredRuntimeDevice)


# ---------------------------------------------------------------------------
# 2. DeviceRegistry record → RegisteredRuntimeDevice
# ---------------------------------------------------------------------------

class TestDeviceRegistryProjection:
    """DeviceRegistry record projects correctly into the canonical contract."""

    def test_identity_domain(self):
        from contracts.registered_runtime_device import from_device_registry_record
        m = _registry_device(device_id="reg_id_01", name="Registry Server")
        c = from_device_registry_record(m)
        assert c.device_id == "reg_id_01"
        assert c.device_name == "Registry Server"

    def test_registration_domain(self):
        from contracts.registered_runtime_device import from_device_registry_record, RuntimeDevicePlatform
        m = _registry_device(device_type="windows")
        c = from_device_registry_record(m)
        assert c.platform in (RuntimeDevicePlatform.WINDOWS, "windows")

    def test_runtime_presence_online(self):
        from contracts.registered_runtime_device import from_device_registry_record
        m = _registry_device(status="online")
        c = from_device_registry_record(m)
        assert c.online is True

    def test_capability_domain_from_objects(self):
        from contracts.registered_runtime_device import from_device_registry_record
        cap1 = MagicMock()
        cap1.name = "keyboard"
        cap2 = MagicMock()
        cap2.name = "screen"
        m = _registry_device(capabilities=[cap1, cap2])
        c = from_device_registry_record(m)
        assert "keyboard" in c.capabilities.capabilities
        assert "screen" in c.capabilities.capabilities

    def test_participation_domain_groups_and_tags(self):
        from contracts.registered_runtime_device import from_device_registry_record
        m = _registry_device(groups=["team_a", "team_b"], tags=["production", "tier1"])
        c = from_device_registry_record(m)
        # domain 5: participation
        assert "team_a" in c.participation_hints.groups
        assert "production" in c.participation_hints.tags

    def test_last_seen_carried(self):
        from contracts.registered_runtime_device import from_device_registry_record
        ts = time.time()
        m = _registry_device(last_seen=ts)
        c = from_device_registry_record(m)
        assert c.last_seen is not None
        assert abs(c.last_seen - ts) < 1.0

    def test_produces_valid_contract_instance(self):
        from contracts.registered_runtime_device import from_device_registry_record, RegisteredRuntimeDevice
        c = from_device_registry_record(_registry_device())
        assert isinstance(c, RegisteredRuntimeDevice)

    def test_string_status_not_enum(self):
        """Registry records with a plain string status are handled correctly."""
        from contracts.registered_runtime_device import from_device_registry_record
        m = MagicMock()
        m.device_id = "reg_str_status"
        m.name = "Plain Status Device"
        m.device_type = "linux"
        m.status = "online"
        m.capabilities = []
        m.last_seen = None
        m.last_heartbeat = None
        m.groups = []
        m.tags = []
        m.metadata = {}
        c = from_device_registry_record(m)
        assert c.device_id == "reg_str_status"
        assert c.online is True


# ---------------------------------------------------------------------------
# 3. Android-originated state → RegisteredRuntimeDevice
# ---------------------------------------------------------------------------

class TestAndroidProjection:
    """Android registration payload projects correctly into the canonical contract."""

    def test_identity_domain(self):
        from contracts.registered_runtime_device import from_android_registration
        c = from_android_registration(_android_payload(device_id="a_01", name="Test Phone"))
        assert c.device_id == "a_01"
        assert c.device_name == "Test Phone"

    def test_registration_domain_android_phone(self):
        from contracts.registered_runtime_device import (
            from_android_registration,
            RuntimeDevicePlatform,
            RuntimeDeviceFormFactor,
        )
        c = from_android_registration(_android_payload())
        assert c.platform in (RuntimeDevicePlatform.ANDROID, "android")
        assert c.form_factor in (RuntimeDeviceFormFactor.PHONE, "phone")

    def test_runtime_presence_connected(self):
        from contracts.registered_runtime_device import from_android_registration, RuntimeConnectionState
        c = from_android_registration(_android_payload())
        assert c.online is True
        assert c.connection.state in (RuntimeConnectionState.CONNECTED, "connected")
        assert c.connection.transport == "websocket"

    def test_capability_domain_list(self):
        from contracts.registered_runtime_device import from_android_registration
        c = from_android_registration(_android_payload(capabilities=["screen", "gps", "camera"]))
        assert "screen" in c.capabilities.capabilities
        assert "gps" in c.capabilities.capabilities

    def test_capability_domain_bitmask_zero(self):
        from contracts.registered_runtime_device import from_android_registration
        data = _android_payload()
        data["capabilities"] = 0
        c = from_android_registration(data)
        # zero bitmask → empty or bridged list; should not raise
        assert isinstance(c.capabilities.capabilities, list)

    def test_topology_hint_runtime_version(self):
        from contracts.registered_runtime_device import from_android_registration
        c = from_android_registration(_android_payload(app_version="3.2.0"))
        assert c.autonomy.runtime_version == "3.2.0"
        assert c.autonomy.supports_remote_handoff is True
        assert c.autonomy.runtime_enabled is True

    def test_metadata_carries_model_os(self):
        from contracts.registered_runtime_device import from_android_registration
        c = from_android_registration(_android_payload(model="Pixel 9", os_version="15"))
        assert c.metadata.get("model") == "Pixel 9"
        assert c.metadata.get("os_version") == "15"

    def test_missing_device_id_generates_one(self):
        from contracts.registered_runtime_device import from_android_registration
        c = from_android_registration({"name": "No ID Phone"})
        assert c.device_id.startswith("android_")

    def test_produces_valid_contract_instance(self):
        from contracts.registered_runtime_device import from_android_registration, RegisteredRuntimeDevice
        c = from_android_registration(_android_payload())
        assert isinstance(c, RegisteredRuntimeDevice)


# ---------------------------------------------------------------------------
# 4. Router-derived runtime state → RegisteredRuntimeDevice
# ---------------------------------------------------------------------------

class TestRouterProjection:
    """Router device object projects correctly into the canonical contract."""

    def test_identity_domain(self):
        from contracts.registered_runtime_device import from_router_device
        m = _router_device(device_id="rt_01", device_name="Router Node")
        c = from_router_device(m)
        assert c.device_id == "rt_01"
        assert c.device_name == "Router Node"

    def test_runtime_presence_connected_has_websocket(self):
        from contracts.registered_runtime_device import from_router_device, RuntimeConnectionState
        m = _router_device(websocket=MagicMock())
        c = from_router_device(m)
        assert c.online is True
        assert c.connection.state in (RuntimeConnectionState.CONNECTED, "connected")

    def test_runtime_presence_disconnected_no_websocket(self):
        from contracts.registered_runtime_device import from_router_device, RuntimeConnectionState
        m = _router_device(websocket=None)
        c = from_router_device(m)
        assert c.online is False
        assert c.connection.state in (RuntimeConnectionState.DISCONNECTED, "disconnected")

    def test_capability_domain_string_list(self):
        from contracts.registered_runtime_device import from_router_device
        m = _router_device(capabilities=["screen", "keyboard", "microphone"])
        c = from_router_device(m)
        assert "keyboard" in c.capabilities.capabilities

    def test_capability_domain_objects_with_name(self):
        from contracts.registered_runtime_device import from_router_device
        cap1 = MagicMock()
        cap1.name = "camera"
        m = _router_device(capabilities=[cap1])
        c = from_router_device(m)
        assert "camera" in c.capabilities.capabilities

    def test_produces_valid_contract_instance(self):
        from contracts.registered_runtime_device import from_router_device, RegisteredRuntimeDevice
        c = from_router_device(_router_device())
        assert isinstance(c, RegisteredRuntimeDevice)


# ---------------------------------------------------------------------------
# 5. Agent-backed / DeviceAgentManager → RegisteredRuntimeDevice
# ---------------------------------------------------------------------------

class TestAgentManagerProjection:
    """DeviceAgentManager DeviceInfo projects correctly into the canonical contract."""

    def test_identity_domain(self):
        from contracts.registered_runtime_device import from_device_agent_manager_record
        m = _agent_device_info(device_id="ag_01", device_name="Agent IoT")
        c = from_device_agent_manager_record(m)
        assert c.device_id == "ag_01"
        assert c.device_name == "Agent IoT"

    def test_registration_domain_device_type_enum(self):
        from contracts.registered_runtime_device import from_device_agent_manager_record
        m = _agent_device_info(device_type="iot")
        c = from_device_agent_manager_record(m)
        assert c.device_type == "iot"

    def test_runtime_presence_online(self):
        from contracts.registered_runtime_device import from_device_agent_manager_record
        m = _agent_device_info(status="online")
        c = from_device_agent_manager_record(m)
        assert c.online is True

    def test_runtime_presence_offline(self):
        from contracts.registered_runtime_device import from_device_agent_manager_record
        status_mock = MagicMock()
        status_mock.value = "offline"
        m = _agent_device_info(status="offline", status_obj=status_mock)
        c = from_device_agent_manager_record(m)
        assert c.online is False

    def test_capability_domain_enum_value(self):
        from contracts.registered_runtime_device import from_device_agent_manager_record
        cap = MagicMock()
        cap.value = "gps"
        m = _agent_device_info(capabilities=[cap])
        c = from_device_agent_manager_record(m)
        assert "gps" in c.capabilities.capabilities

    def test_capability_domain_enum_name_fallback(self):
        """Capabilities with only .name (not .value) are also handled."""
        from contracts.registered_runtime_device import from_device_agent_manager_record
        cap = MagicMock(spec=["name"])
        cap.name = "accelerometer"
        m = _agent_device_info(capabilities=[cap])
        c = from_device_agent_manager_record(m)
        assert "accelerometer" in c.capabilities.capabilities

    def test_capability_domain_string_caps(self):
        from contracts.registered_runtime_device import from_device_agent_manager_record
        m = _agent_device_info(capabilities=["screen", "microphone"])
        c = from_device_agent_manager_record(m)
        assert "screen" in c.capabilities.capabilities
        assert "microphone" in c.capabilities.capabilities

    def test_last_heartbeat_datetime_to_float(self):
        from contracts.registered_runtime_device import from_device_agent_manager_record
        lh = datetime(2026, 3, 22, 10, 0, 0, tzinfo=timezone.utc)
        m = _agent_device_info(last_heartbeat=lh)
        c = from_device_agent_manager_record(m)
        assert c.last_seen is not None
        assert isinstance(c.last_seen, float)

    def test_metadata_preserved(self):
        from contracts.registered_runtime_device import from_device_agent_manager_record
        m = _agent_device_info(metadata={"region": "eu-central"})
        c = from_device_agent_manager_record(m)
        assert c.metadata.get("region") == "eu-central"

    def test_registered_at_in_metadata(self):
        from contracts.registered_runtime_device import from_device_agent_manager_record
        reg_at = datetime(2026, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
        m = _agent_device_info(registered_at=reg_at, metadata={})
        c = from_device_agent_manager_record(m)
        assert "registered_at" in c.metadata

    def test_registered_at_none_does_not_pollute_metadata(self):
        from contracts.registered_runtime_device import from_device_agent_manager_record
        m = _agent_device_info(registered_at=None, metadata={})
        c = from_device_agent_manager_record(m)
        assert "registered_at" not in c.metadata

    def test_topology_hint_runtime_enabled_when_online(self):
        from contracts.registered_runtime_device import from_device_agent_manager_record
        m = _agent_device_info(status="online")
        c = from_device_agent_manager_record(m)
        assert c.autonomy.runtime_enabled is True

    def test_missing_device_id_generates_one(self):
        from contracts.registered_runtime_device import from_device_agent_manager_record
        m = MagicMock()
        m.device_id = ""
        m.device_name = "Unnamed"
        status_mock = MagicMock()
        status_mock.value = "offline"
        m.status = status_mock
        device_type_mock = MagicMock()
        device_type_mock.value = "iot"
        m.device_type = device_type_mock
        m.capabilities = []
        m.metadata = {}
        m.last_heartbeat = None
        m.registered_at = None
        c = from_device_agent_manager_record(m)
        assert c.device_id.startswith("dev_")

    def test_produces_valid_contract_instance(self):
        from contracts.registered_runtime_device import (
            from_device_agent_manager_record,
            RegisteredRuntimeDevice,
        )
        c = from_device_agent_manager_record(_agent_device_info())
        assert isinstance(c, RegisteredRuntimeDevice)

    def test_exception_in_projection_falls_back_to_minimal(self):
        """Even a completely broken object must return a minimal contract."""
        from contracts.registered_runtime_device import from_device_agent_manager_record
        # Pass an object that will raise on almost all attribute access
        class Broken:
            @property
            def device_id(self):
                raise RuntimeError("broken")
        c = from_device_agent_manager_record(Broken())
        assert c.device_id.startswith("dev_")


# ---------------------------------------------------------------------------
# 6. Serialisation stability and graceful partial-field handling
# ---------------------------------------------------------------------------

class TestSerialisationStability:
    """Contract serialises stably from every source."""

    def test_udm_to_json_and_back(self):
        from contracts.registered_runtime_device import from_udm_device, RegisteredRuntimeDevice
        c = from_udm_device(_udm_device())
        raw = c.to_json()
        assert json.loads(raw)["device_id"] == "udm_001"
        # round-trip
        c2 = RegisteredRuntimeDevice.from_dict(json.loads(raw))
        assert c2.device_id == c.device_id

    def test_registry_to_json_and_back(self):
        from contracts.registered_runtime_device import from_device_registry_record, RegisteredRuntimeDevice
        c = from_device_registry_record(_registry_device())
        d = c.to_dict()
        c2 = RegisteredRuntimeDevice.from_dict(d)
        assert c2.device_id == c.device_id

    def test_android_to_json_and_back(self):
        from contracts.registered_runtime_device import from_android_registration, RegisteredRuntimeDevice
        c = from_android_registration(_android_payload())
        raw = c.to_json()
        c2 = RegisteredRuntimeDevice.from_dict(json.loads(raw))
        assert c2.device_id == c.device_id
        assert c2.online == c.online

    def test_router_to_json_and_back(self):
        from contracts.registered_runtime_device import from_router_device, RegisteredRuntimeDevice
        c = from_router_device(_router_device())
        d = c.to_dict()
        c2 = RegisteredRuntimeDevice.from_dict(d)
        assert c2.device_id == c.device_id

    def test_agent_manager_to_json_and_back(self):
        from contracts.registered_runtime_device import (
            from_device_agent_manager_record,
            RegisteredRuntimeDevice,
        )
        c = from_device_agent_manager_record(_agent_device_info())
        raw = c.to_json()
        c2 = RegisteredRuntimeDevice.from_dict(json.loads(raw))
        assert c2.device_id == c.device_id

    def test_all_required_top_level_keys_present(self):
        """to_dict() must always carry all six information-domain keys."""
        from contracts.registered_runtime_device import RegisteredRuntimeDevice
        d = RegisteredRuntimeDevice(device_id="stability_01").to_dict()
        required = {
            "device_id", "device_name", "owner_id",
            "platform", "form_factor", "device_type",
            "status", "online", "last_seen",
            "connection", "capabilities", "autonomy",
            "session_presence", "participation_hints", "metadata",
        }
        assert required <= set(d.keys()), f"Missing keys: {required - set(d.keys())}"

    def test_partial_optional_fields_do_not_raise(self):
        from contracts.registered_runtime_device import build_registered_runtime_device
        c = build_registered_runtime_device(
            device_id="partial_01",
            capabilities=None,
            groups=None,
            tags=None,
            metadata=None,
        )
        assert c.capabilities.capabilities == []
        assert c.participation_hints.groups == []
        assert c.metadata == {}

    def test_all_sources_json_serialisable(self):
        """All source projections must produce JSON-serialisable output."""
        from contracts.registered_runtime_device import (
            from_udm_device,
            from_device_registry_record,
            from_android_registration,
            from_router_device,
            from_device_agent_manager_record,
        )
        contracts = [
            from_udm_device(_udm_device()),
            from_device_registry_record(_registry_device()),
            from_android_registration(_android_payload()),
            from_router_device(_router_device()),
            from_device_agent_manager_record(_agent_device_info()),
        ]
        for c in contracts:
            # Must not raise
            payload = json.loads(c.to_json())
            assert "device_id" in payload


# ---------------------------------------------------------------------------
# 7. Canonical authority — new adapter exported from contracts and core.unified
# ---------------------------------------------------------------------------

class TestCanonicalAuthorityExports:
    """``from_device_agent_manager_record`` is accessible from every public import path."""

    def test_importable_from_contracts_module(self):
        from contracts.registered_runtime_device import from_device_agent_manager_record
        assert callable(from_device_agent_manager_record)

    def test_importable_from_contracts_package_root(self):
        from contracts import from_device_agent_manager_record
        assert callable(from_device_agent_manager_record)

    def test_importable_from_core_unified(self):
        from core.unified import from_device_agent_manager_record
        assert callable(from_device_agent_manager_record)

    def test_contracts_all_includes_new_adapter(self):
        import contracts as c_pkg
        assert "from_device_agent_manager_record" in c_pkg.__all__

    def test_existing_adapters_still_exported(self):
        """PR-5 must not break existing PR-29 exports."""
        from contracts import (
            from_udm_device,
            from_router_device,
            from_android_registration,
            from_device_registry_record,
            RegisteredRuntimeDevice,
        )
        for sym in (from_udm_device, from_router_device, from_android_registration,
                    from_device_registry_record, RegisteredRuntimeDevice):
            assert sym is not None


# ---------------------------------------------------------------------------
# 8. Six information domains — explicit coverage
# ---------------------------------------------------------------------------

class TestSixInformationDomains:
    """Each canonical information domain is populated from the builder."""

    def _full_contract(self):
        from contracts.registered_runtime_device import build_registered_runtime_device
        return build_registered_runtime_device(
            device_id="domain_test_01",
            device_name="Full Domain Device",
            owner_id="owner_01",
            platform="android",
            form_factor="phone",
            device_type="android_phone",
            status="online",
            last_seen=1234567890.0,
            connection_state="connected",
            transport="websocket",
            endpoint="ws://host:8765",
            ip_address="10.0.0.1",
            port=8765,
            capabilities=["screen", "camera"],
            capability_flags=3,
            supported_actions=["click", "swipe"],
            runtime_enabled=True,
            supports_local_autonomy=True,
            supports_remote_handoff=True,
            runtime_id="rt_001",
            runtime_version="3.0",
            active_session_ids=["sess_1"],
            current_task_id="task_1",
            pending_task_ids=["task_2"],
            body_mesh_roles=["action"],
            is_primary_body=True,
            groups=["mobile"],
            tags=["test"],
            metadata={"key": "val"},
        )

    def test_domain_1_identity(self):
        c = self._full_contract()
        assert c.device_id == "domain_test_01"
        assert c.device_name == "Full Domain Device"
        assert c.owner_id == "owner_01"

    def test_domain_2_registration(self):
        c = self._full_contract()
        assert c.platform in ("android", "ANDROID")
        assert c.form_factor in ("phone", "PHONE")
        assert c.device_type == "android_phone"

    def test_domain_3_runtime_presence(self):
        c = self._full_contract()
        assert c.status in ("online", "ONLINE")
        assert c.online is True
        assert c.last_seen == 1234567890.0
        assert c.connection.transport == "websocket"
        assert c.connection.ip_address == "10.0.0.1"
        assert c.connection.port == 8765

    def test_domain_4_capability(self):
        c = self._full_contract()
        assert "screen" in c.capabilities.capabilities
        assert "camera" in c.capabilities.capabilities
        assert c.capabilities.capability_flags == 3
        assert "click" in c.capabilities.supported_actions

    def test_domain_5_participation(self):
        c = self._full_contract()
        assert "sess_1" in c.session_presence.active_session_ids
        assert c.session_presence.current_task_id == "task_1"
        assert "task_2" in c.session_presence.pending_task_ids
        assert "mobile" in c.participation_hints.groups
        assert "test" in c.participation_hints.tags

    def test_domain_6_topology_runtime_hints(self):
        c = self._full_contract()
        assert c.autonomy.runtime_enabled is True
        assert c.autonomy.supports_local_autonomy is True
        assert c.autonomy.supports_remote_handoff is True
        assert c.autonomy.runtime_id == "rt_001"
        assert c.autonomy.runtime_version == "3.0"
        assert c.participation_hints.body_mesh_roles == ["action"]
        assert c.participation_hints.is_primary_body is True
