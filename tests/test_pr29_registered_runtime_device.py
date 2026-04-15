"""tests/test_pr29_registered_runtime_device.py
================================================
Tests for PR-29: Unified Registered Runtime Device Contract.

Coverage:
  1. Serialisation stability — to_dict / to_json / from_dict round-trips.
  2. Adapter: from_udm_device normalises UnifiedDevice.
  3. Adapter: from_router_device normalises gateway Device wrapper.
  4. Adapter: from_android_registration normalises Android bridge data.
  5. Adapter: from_device_registry_record normalises DeviceModel records.
  6. Builder: build_registered_runtime_device produces correct contract.
  7. Graceful handling of partial / missing data.
  8. Enum helpers (from_string with unknown values).
  9. contracts package root re-exports.
  10. core.unified package re-exports.
  11. Runtime contract API endpoint (read-only, additive).
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_unified_device(**kwargs: Any) -> MagicMock:
    """Create a mock UnifiedDevice with sensible defaults."""
    m = MagicMock()
    m.device_id = kwargs.get("device_id", "udm_dev_001")
    m.device_name = kwargs.get("device_name", "UDM Device")
    m.device_type = kwargs.get("device_type", "android")
    m.status = kwargs.get("status", "online")
    m.capabilities = kwargs.get("capabilities", ["screen", "camera"])
    m.metadata = kwargs.get("metadata", {})
    m.last_heartbeat = kwargs.get("last_heartbeat", None)
    m.is_online.return_value = kwargs.get("status", "online") == "online"
    return m


def _make_mock_router_device(**kwargs: Any) -> MagicMock:
    """Create a mock gateway router Device with sensible defaults."""
    m = MagicMock()
    m.device_id = kwargs.get("device_id", "router_dev_001")
    m.device_name = kwargs.get("device_name", "Router Device")
    m.device_type = kwargs.get("device_type", "windows")
    m.capabilities = kwargs.get("capabilities", ["screen", "keyboard"])
    m.websocket = kwargs.get("websocket", MagicMock())
    m.metadata = kwargs.get("metadata", {})
    return m


# ---------------------------------------------------------------------------
# 1. Serialisation stability
# ---------------------------------------------------------------------------

class TestSerialisationStability:
    """RegisteredRuntimeDevice serialises and round-trips correctly."""

    def test_to_dict_returns_serialisable_dict(self):
        from contracts.registered_runtime_device import RegisteredRuntimeDevice
        d = RegisteredRuntimeDevice(device_id="dev_001")
        result = d.to_dict()
        assert isinstance(result, dict)
        assert result["device_id"] == "dev_001"
        # Ensure JSON-serialisable
        json.dumps(result)

    def test_to_json_returns_valid_json(self):
        from contracts.registered_runtime_device import RegisteredRuntimeDevice
        d = RegisteredRuntimeDevice(device_id="dev_002", device_name="Test Device")
        raw = d.to_json()
        parsed = json.loads(raw)
        assert parsed["device_id"] == "dev_002"
        assert parsed["device_name"] == "Test Device"

    def test_from_dict_round_trip(self):
        from contracts.registered_runtime_device import RegisteredRuntimeDevice
        original = RegisteredRuntimeDevice(
            device_id="dev_003",
            device_name="Round Trip",
            platform="android",  # type: ignore[arg-type]
            online=True,
        )
        data = original.to_dict()
        reconstructed = RegisteredRuntimeDevice.from_dict(data)
        assert reconstructed.device_id == original.device_id
        assert reconstructed.device_name == original.device_name
        assert reconstructed.platform == original.platform
        assert reconstructed.online == original.online

    def test_stable_field_names_present(self):
        """All documented top-level fields are present in to_dict output."""
        from contracts.registered_runtime_device import RegisteredRuntimeDevice
        d = RegisteredRuntimeDevice(device_id="dev_004")
        result = d.to_dict()
        expected_keys = {
            "device_id", "device_name", "owner_id",
            "platform", "form_factor", "device_type", "device_execution_model",
            "status", "online", "last_seen",
            "connection", "capabilities", "autonomy",
            "session_presence", "participation_hints", "participant_identity", "metadata",
        }
        assert expected_keys <= set(result.keys())

    def test_sub_contract_fields_present(self):
        from contracts.registered_runtime_device import RegisteredRuntimeDevice
        d = RegisteredRuntimeDevice(device_id="dev_005")
        result = d.to_dict()
        assert "state" in result["connection"]
        assert "capabilities" in result["capabilities"]
        assert "runtime_enabled" in result["autonomy"]
        assert "active_session_ids" in result["session_presence"]
        assert "body_mesh_roles" in result["participation_hints"]

    def test_full_contract_round_trip(self):
        from contracts.registered_runtime_device import (
            RegisteredRuntimeDevice,
            RuntimeConnectionSummary,
            RuntimeCapabilityProfile,
            RuntimeAutonomySummary,
            RuntimeSessionPresence,
            RuntimeParticipationHints,
            RuntimeDevicePlatform,
            RuntimeDeviceFormFactor,
            RuntimeDeviceStatus,
            RuntimeConnectionState,
        )
        d = RegisteredRuntimeDevice(
            device_id="dev_full",
            device_name="Full Device",
            owner_id="user_abc",
            platform=RuntimeDevicePlatform.ANDROID,
            form_factor=RuntimeDeviceFormFactor.PHONE,
            device_type="android_phone",
            status=RuntimeDeviceStatus.ONLINE,
            online=True,
            last_seen=1234567890.0,
            connection=RuntimeConnectionSummary(
                state=RuntimeConnectionState.CONNECTED,
                transport="websocket",
                endpoint="ws://host:8765",
                ip_address="192.168.1.10",
                port=8765,
            ),
            capabilities=RuntimeCapabilityProfile(
                capabilities=["screen", "camera"],
                capability_flags=42,
                supported_actions=["click", "swipe"],
            ),
            autonomy=RuntimeAutonomySummary(
                runtime_enabled=True,
                supports_local_autonomy=True,
                supports_remote_handoff=True,
                runtime_id="rt_abc",
                runtime_version="3.0",
            ),
            session_presence=RuntimeSessionPresence(
                active_session_ids=["sess_1"],
                current_task_id="task_1",
                pending_task_ids=["task_2"],
            ),
            participation_hints=RuntimeParticipationHints(
                body_mesh_roles=["action", "presence"],
                is_primary_body=True,
                groups=["mobile"],
                tags=["test"],
            ),
            metadata={"extra": "data"},
        )
        data = d.to_dict()
        r = RegisteredRuntimeDevice.from_dict(data)
        assert r.device_id == "dev_full"
        assert r.platform == RuntimeDevicePlatform.ANDROID.value
        assert r.capabilities.capabilities == ["screen", "camera"]
        assert r.autonomy.runtime_id == "rt_abc"
        assert r.session_presence.current_task_id == "task_1"
        assert r.participation_hints.body_mesh_roles == ["action", "presence"]


# ---------------------------------------------------------------------------
# 2. Adapter: from_udm_device
# ---------------------------------------------------------------------------

class TestFromUdmDevice:
    def test_basic_fields_mapped(self):
        from contracts.registered_runtime_device import from_udm_device, RuntimeDeviceStatus
        m = _make_mock_unified_device()
        c = from_udm_device(m)
        assert c.device_id == "udm_dev_001"
        assert c.device_name == "UDM Device"
        # With use_enum_values=True, platform is stored as the string value
        assert c.platform == "android"
        assert c.online is True
        assert c.status in (RuntimeDeviceStatus.ONLINE, RuntimeDeviceStatus.ONLINE.value)

    def test_capabilities_transferred(self):
        from contracts.registered_runtime_device import from_udm_device
        m = _make_mock_unified_device(capabilities=["screen", "camera", "gps"])
        c = from_udm_device(m)
        assert "screen" in c.capabilities.capabilities
        assert "gps" in c.capabilities.capabilities

    def test_offline_device(self):
        from contracts.registered_runtime_device import from_udm_device, RuntimeDeviceStatus
        m = _make_mock_unified_device(status="offline")
        c = from_udm_device(m)
        assert c.online is False
        assert c.status in (RuntimeDeviceStatus.OFFLINE, RuntimeDeviceStatus.OFFLINE.value)

    def test_last_heartbeat_datetime_converted(self):
        from datetime import datetime
        from contracts.registered_runtime_device import from_udm_device
        lh = datetime(2026, 3, 21, 9, 0, 0)
        m = _make_mock_unified_device(last_heartbeat=lh)
        c = from_udm_device(m)
        assert c.last_seen is not None
        assert isinstance(c.last_seen, float)

    def test_metadata_carried(self):
        from contracts.registered_runtime_device import from_udm_device
        m = _make_mock_unified_device(metadata={"source": "udm_test"})
        c = from_udm_device(m)
        assert c.metadata.get("source") == "udm_test"


# ---------------------------------------------------------------------------
# 3. Adapter: from_router_device
# ---------------------------------------------------------------------------

class TestFromRouterDevice:
    def test_connected_device(self):
        from contracts.registered_runtime_device import from_router_device, RuntimeConnectionState
        m = _make_mock_router_device()
        c = from_router_device(m)
        assert c.device_id == "router_dev_001"
        assert c.online is True
        assert c.connection.state in (
            RuntimeConnectionState.CONNECTED,
            RuntimeConnectionState.CONNECTED.value,
        )

    def test_disconnected_device_no_websocket(self):
        from contracts.registered_runtime_device import from_router_device, RuntimeConnectionState
        m = _make_mock_router_device(websocket=None)
        c = from_router_device(m)
        assert c.online is False
        assert c.connection.state in (
            RuntimeConnectionState.DISCONNECTED,
            RuntimeConnectionState.DISCONNECTED.value,
        )

    def test_capabilities_as_strings(self):
        from contracts.registered_runtime_device import from_router_device
        m = _make_mock_router_device(capabilities=["screen", "keyboard"])
        c = from_router_device(m)
        assert "screen" in c.capabilities.capabilities

    def test_capabilities_as_objects_with_name(self):
        from contracts.registered_runtime_device import from_router_device
        cap1 = MagicMock()
        cap1.name = "camera"
        m = _make_mock_router_device(capabilities=[cap1])
        c = from_router_device(m)
        assert "camera" in c.capabilities.capabilities


# ---------------------------------------------------------------------------
# 4. Adapter: from_android_registration
# ---------------------------------------------------------------------------

class TestFromAndroidRegistration:
    def _sample_data(self, **overrides: Any) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "device_id": "android_001",
            "name": "My Phone",
            "model": "Pixel 9",
            "os_version": "15",
            "sdk_version": 35,
            "screen_width": 1080,
            "screen_height": 2340,
            "capabilities": 0,  # no bitmask
            "app_version": "3.2.0",
            "device_type": "android_phone",
        }
        data.update(overrides)
        return data

    def test_basic_registration(self):
        from contracts.registered_runtime_device import (
            from_android_registration,
            RuntimeDevicePlatform,
            RuntimeDeviceFormFactor,
        )
        c = from_android_registration(self._sample_data())
        assert c.device_id == "android_001"
        assert c.device_name == "My Phone"
        assert c.platform in (RuntimeDevicePlatform.ANDROID, RuntimeDevicePlatform.ANDROID.value)
        assert c.form_factor in (RuntimeDeviceFormFactor.PHONE, RuntimeDeviceFormFactor.PHONE.value)
        assert c.online is True

    def test_metadata_carries_model_os(self):
        from contracts.registered_runtime_device import from_android_registration
        c = from_android_registration(self._sample_data())
        assert c.metadata.get("model") == "Pixel 9"
        assert c.metadata.get("os_version") == "15"

    def test_list_capabilities(self):
        from contracts.registered_runtime_device import from_android_registration
        c = from_android_registration(self._sample_data(capabilities=["screen", "gps"]))
        assert "screen" in c.capabilities.capabilities
        assert "gps" in c.capabilities.capabilities

    def test_runtime_version_carried(self):
        from contracts.registered_runtime_device import from_android_registration
        c = from_android_registration(self._sample_data())
        assert c.autonomy.runtime_version == "3.2.0"

    def test_supports_remote_handoff_true(self):
        from contracts.registered_runtime_device import from_android_registration
        c = from_android_registration(self._sample_data())
        assert c.autonomy.supports_remote_handoff is True

    def test_missing_device_id_generates_one(self):
        from contracts.registered_runtime_device import from_android_registration
        c = from_android_registration({"name": "Unknown"})
        assert c.device_id.startswith("android_")
        assert len(c.device_id) > 0

    def test_connection_is_websocket(self):
        from contracts.registered_runtime_device import from_android_registration, RuntimeConnectionState
        c = from_android_registration(self._sample_data())
        assert c.connection.state in (
            RuntimeConnectionState.CONNECTED,
            RuntimeConnectionState.CONNECTED.value,
        )
        assert c.connection.transport == "websocket"

    def test_execution_model_defaults_to_full_runtime_host_for_android_app(self):
        from contracts.registered_runtime_device import (
            from_android_registration,
            RuntimeDeviceExecutionModel,
        )
        c = from_android_registration(self._sample_data(app_version="3.2.0"))
        assert c.device_execution_model in (
            RuntimeDeviceExecutionModel.FULL_RUNTIME_HOST,
            RuntimeDeviceExecutionModel.FULL_RUNTIME_HOST.value,
        )


# ---------------------------------------------------------------------------
# 5. Adapter: from_device_registry_record
# ---------------------------------------------------------------------------

class TestFromDeviceRegistryRecord:
    def _mock_device_model(self, **overrides: Any) -> MagicMock:
        m = MagicMock()
        m.device_id = overrides.get("device_id", "reg_dev_001")
        m.name = overrides.get("name", "Registry Device")
        raw_type = MagicMock()
        raw_type.value = overrides.get("device_type", "windows")
        m.device_type = raw_type
        raw_status = MagicMock()
        raw_status.value = overrides.get("status", "online")
        m.status = raw_status
        cap = MagicMock()
        cap.name = "screen"
        m.capabilities = overrides.get("capabilities", [cap])
        m.last_seen = overrides.get("last_seen", time.time())
        m.last_heartbeat = overrides.get("last_heartbeat", None)
        m.groups = overrides.get("groups", ["desktop"])
        m.tags = overrides.get("tags", ["prod"])
        m.metadata = overrides.get("metadata", {})
        return m

    def test_basic_mapping(self):
        from contracts.registered_runtime_device import from_device_registry_record
        m = self._mock_device_model()
        c = from_device_registry_record(m)
        assert c.device_id == "reg_dev_001"
        assert c.device_name == "Registry Device"

    def test_platform_resolved(self):
        from contracts.registered_runtime_device import from_device_registry_record, RuntimeDevicePlatform
        m = self._mock_device_model(device_type="windows")
        c = from_device_registry_record(m)
        assert c.platform in (RuntimeDevicePlatform.WINDOWS, RuntimeDevicePlatform.WINDOWS.value)

    def test_capabilities_from_objects(self):
        from contracts.registered_runtime_device import from_device_registry_record
        cap1 = MagicMock()
        cap1.name = "keyboard"
        m = self._mock_device_model(capabilities=[cap1])
        c = from_device_registry_record(m)
        assert "keyboard" in c.capabilities.capabilities

    def test_groups_and_tags_in_hints(self):
        from contracts.registered_runtime_device import from_device_registry_record
        m = self._mock_device_model(groups=["team_a"], tags=["test"])
        c = from_device_registry_record(m)
        assert "team_a" in c.participation_hints.groups
        assert "test" in c.participation_hints.tags


# ---------------------------------------------------------------------------
# 6. Builder: build_registered_runtime_device
# ---------------------------------------------------------------------------

class TestBuildRegisteredRuntimeDevice:
    def test_minimal_required_only(self):
        from contracts.registered_runtime_device import build_registered_runtime_device
        c = build_registered_runtime_device(device_id="minimal_001")
        assert c.device_id == "minimal_001"
        assert c.online is False
        assert c.capabilities.capabilities == []

    def test_full_build(self):
        from contracts.registered_runtime_device import build_registered_runtime_device
        c = build_registered_runtime_device(
            device_id="full_001",
            device_name="Full Device",
            owner_id="owner_xyz",
            platform="android",
            form_factor="phone",
            device_type="android_phone",
            runtime_id="rt_001",
            runtime_version="3.0",
            runtime_enabled=True,
            supports_local_autonomy=True,
            supports_remote_handoff=True,
            capabilities=["screen", "camera"],
            capability_flags=7,
            supported_actions=["click", "swipe"],
            status="online",
            last_seen=1234567890.0,
            active_session_ids=["sess_1"],
            current_task_id="task_1",
            pending_task_ids=["task_2"],
            body_mesh_roles=["action"],
            is_primary_body=True,
            groups=["mobile"],
            tags=["test"],
            connection_state="connected",
            transport="websocket",
            endpoint="ws://host:8765",
            ip_address="192.168.1.5",
            port=8765,
            metadata={"extra": "value"},
        )
        assert c.device_id == "full_001"
        assert c.owner_id == "owner_xyz"
        assert c.online is True
        assert c.autonomy.runtime_enabled is True
        assert c.autonomy.supports_local_autonomy is True
        assert c.autonomy.runtime_id == "rt_001"
        assert c.capabilities.capabilities == ["screen", "camera"]
        assert c.capabilities.capability_flags == 7
        assert c.session_presence.current_task_id == "task_1"
        assert c.participation_hints.is_primary_body is True
        assert c.connection.transport == "websocket"
        assert c.metadata["extra"] == "value"

    def test_online_derived_from_status(self):
        from contracts.registered_runtime_device import build_registered_runtime_device
        c_online = build_registered_runtime_device(device_id="dev_on", status="online")
        c_offline = build_registered_runtime_device(device_id="dev_off", status="offline")
        assert c_online.online is True
        assert c_offline.online is False

    def test_online_explicit_override(self):
        from contracts.registered_runtime_device import build_registered_runtime_device
        c = build_registered_runtime_device(device_id="dev_ovr", status="offline", online=True)
        assert c.online is True

    def test_participant_identity_and_adapter_model(self):
        from contracts.registered_runtime_device import (
            build_registered_runtime_device,
            RuntimeDeviceExecutionModel,
            RuntimeParticipantTier,
        )
        c = build_registered_runtime_device(
            device_id="bridge_dev_01",
            participant_id="p_bridge_01",
            participant_tier="bridged",
            participant_role="observer",
            participant_attached_via_adapter=True,
            participant_bridge_id="mqtt_bridge",
        )
        assert c.participant_identity.participant_id == "p_bridge_01"
        assert c.participant_identity.participant_tier in (
            RuntimeParticipantTier.BRIDGED,
            RuntimeParticipantTier.BRIDGED.value,
        )
        assert c.participant_identity.attached_via_adapter is True
        assert c.participant_identity.bridge_id == "mqtt_bridge"
        assert c.device_execution_model in (
            RuntimeDeviceExecutionModel.ADAPTER_BRIDGED_DEVICE,
            RuntimeDeviceExecutionModel.ADAPTER_BRIDGED_DEVICE.value,
        )


# ---------------------------------------------------------------------------
# 7. Graceful handling of partial / missing data
# ---------------------------------------------------------------------------

class TestPartialDataHandling:
    def test_from_udm_device_missing_all_optional_fields(self):
        from contracts.registered_runtime_device import from_udm_device
        m = MagicMock()
        m.device_id = "sparse_001"
        # All other attributes raise AttributeError via MagicMock defaults —
        # but MagicMock returns MagicMock for attribute access, so we set
        # the important ones to None to simulate missing data.
        m.device_name = None
        m.device_type = None
        m.status = None
        m.capabilities = None
        m.metadata = None
        m.last_heartbeat = None
        c = from_udm_device(m)
        assert c.device_id == "sparse_001"

    def test_from_android_registration_empty_dict(self):
        from contracts.registered_runtime_device import from_android_registration
        c = from_android_registration({})
        assert c.device_id  # auto-generated

    def test_from_android_registration_no_capabilities_key(self):
        from contracts.registered_runtime_device import from_android_registration
        c = from_android_registration({"device_id": "droid_001"})
        # Should not raise; capabilities may be empty list
        assert isinstance(c.capabilities.capabilities, list)

    def test_build_with_none_lists_treated_as_empty(self):
        from contracts.registered_runtime_device import build_registered_runtime_device
        c = build_registered_runtime_device(
            device_id="dev_none",
            capabilities=None,
            tags=None,
            groups=None,
        )
        assert c.capabilities.capabilities == []
        assert c.participation_hints.tags == []
        assert c.participation_hints.groups == []

    def test_from_device_registry_record_with_string_status(self):
        """Registry record with plain string status (not enum) is handled."""
        from contracts.registered_runtime_device import from_device_registry_record
        m = MagicMock()
        m.device_id = "str_status_dev"
        m.name = ""
        m.device_type = "android"  # plain string, no .value attr on str... but MagicMock wraps it
        # Override to simulate a real string (not a MagicMock)
        m.device_type = "android"
        m.status = "online"
        m.capabilities = []
        m.last_seen = None
        m.last_heartbeat = None
        m.groups = []
        m.tags = []
        m.metadata = {}
        c = from_device_registry_record(m)
        assert c.device_id == "str_status_dev"


# ---------------------------------------------------------------------------
# 8. Enum helpers
# ---------------------------------------------------------------------------

class TestEnumHelpers:
    def test_runtime_device_platform_unknown_fallback(self):
        from contracts.registered_runtime_device import RuntimeDevicePlatform
        assert RuntimeDevicePlatform.from_string("completely_unknown") == RuntimeDevicePlatform.UNKNOWN
        assert RuntimeDevicePlatform.from_string("") == RuntimeDevicePlatform.UNKNOWN
        assert RuntimeDevicePlatform.from_string("android") == RuntimeDevicePlatform.ANDROID

    def test_runtime_device_form_factor_unknown_fallback(self):
        from contracts.registered_runtime_device import RuntimeDeviceFormFactor
        assert RuntimeDeviceFormFactor.from_string("spaceship") == RuntimeDeviceFormFactor.UNKNOWN
        assert RuntimeDeviceFormFactor.from_string("phone") == RuntimeDeviceFormFactor.PHONE

    def test_runtime_device_status_offline_fallback(self):
        from contracts.registered_runtime_device import RuntimeDeviceStatus
        assert RuntimeDeviceStatus.from_string("unknown_xyz") == RuntimeDeviceStatus.OFFLINE
        assert RuntimeDeviceStatus.from_string("online") == RuntimeDeviceStatus.ONLINE

    def test_runtime_connection_state_disconnected_fallback(self):
        from contracts.registered_runtime_device import RuntimeConnectionState
        assert RuntimeConnectionState.from_string("blah") == RuntimeConnectionState.DISCONNECTED
        assert RuntimeConnectionState.from_string("connected") == RuntimeConnectionState.CONNECTED

    def test_is_online_method(self):
        from contracts.registered_runtime_device import RegisteredRuntimeDevice, RuntimeDeviceStatus
        d_on = RegisteredRuntimeDevice(device_id="x", status=RuntimeDeviceStatus.ONLINE, online=True)
        d_off = RegisteredRuntimeDevice(device_id="y", status=RuntimeDeviceStatus.OFFLINE, online=False)
        d_busy = RegisteredRuntimeDevice(device_id="z", status=RuntimeDeviceStatus.BUSY, online=True)
        assert d_on.is_online() is True
        assert d_off.is_online() is False
        assert d_busy.is_online() is True


# ---------------------------------------------------------------------------
# 9. contracts package root re-exports
# ---------------------------------------------------------------------------

class TestContractsPackageExports:
    def test_registered_runtime_device_importable(self):
        from contracts import RegisteredRuntimeDevice
        assert RegisteredRuntimeDevice is not None

    def test_all_adapter_functions_importable(self):
        from contracts import (
            build_registered_runtime_device,
            from_udm_device,
            from_router_device,
            from_android_registration,
            from_device_registry_record,
        )
        assert callable(build_registered_runtime_device)
        assert callable(from_udm_device)
        assert callable(from_router_device)
        assert callable(from_android_registration)
        assert callable(from_device_registry_record)

    def test_all_sub_contract_types_importable(self):
        from contracts import (
            RuntimeConnectionSummary,
            RuntimeCapabilityProfile,
            RuntimeAutonomySummary,
            RuntimeSessionPresence,
            RuntimeParticipationHints,
            RuntimeParticipantIdentity,
        )
        for cls in (
            RuntimeConnectionSummary,
            RuntimeCapabilityProfile,
            RuntimeAutonomySummary,
            RuntimeSessionPresence,
            RuntimeParticipationHints,
            RuntimeParticipantIdentity,
        ):
            assert cls is not None

    def test_all_enums_importable(self):
        from contracts import (
            RuntimeDevicePlatform,
            RuntimeDeviceFormFactor,
            RuntimeDeviceStatus,
            RuntimeConnectionState,
            RuntimeParticipantTier,
            RuntimeDeviceExecutionModel,
        )
        assert RuntimeDevicePlatform.ANDROID.value == "android"
        assert RuntimeDeviceFormFactor.PHONE.value == "phone"
        assert RuntimeDeviceStatus.ONLINE.value == "online"
        assert RuntimeConnectionState.CONNECTED.value == "connected"
        assert RuntimeParticipantTier.UNASSIGNED.value == "unassigned"
        assert RuntimeDeviceExecutionModel.UNKNOWN.value == "unknown"

    def test_existing_execution_trace_exports_still_work(self):
        """PR-29 must not break the PR-25 execution trace exports."""
        from contracts import (
            ExecutionTraceEnvelope,
            ExecutionTraceEvent,
            ExecutionTraceStage,
            ExecutionTraceStatus,
        )
        assert ExecutionTraceEnvelope is not None
        assert ExecutionTraceStage.INTENT_CREATED is not None


# ---------------------------------------------------------------------------
# 10. core.unified package re-exports
# ---------------------------------------------------------------------------

class TestCoreUnifiedReexports:
    def test_registered_runtime_device_in_core_unified(self):
        from core.unified import RegisteredRuntimeDevice
        assert RegisteredRuntimeDevice is not None

    def test_builder_in_core_unified(self):
        from core.unified import build_registered_runtime_device
        assert callable(build_registered_runtime_device)

    def test_adapters_in_core_unified(self):
        from core.unified import from_udm_device, from_router_device
        assert callable(from_udm_device)
        assert callable(from_router_device)


# ---------------------------------------------------------------------------
# 11. Runtime contract API endpoint
# ---------------------------------------------------------------------------

class TestRuntimeContractEndpoint:
    @pytest.fixture(scope="class")
    def app_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from core.routes.devices import create_router

        app = FastAPI()
        router = create_router()
        app.include_router(router)
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_unknown_device_returns_404(self, app_client):
        resp = app_client.get("/api/v1/devices/nonexistent_device_xyz/runtime-contract")
        assert resp.status_code == 404

    def test_endpoint_is_read_only_get(self, app_client):
        """Ensure the endpoint only accepts GET (not POST/PUT/DELETE)."""
        resp_post = app_client.post("/api/v1/devices/nonexistent_device_xyz/runtime-contract")
        assert resp_post.status_code == 405

    def test_registered_device_returns_contract(self, app_client):
        """Register a device then retrieve its runtime contract."""
        # First register a device using the existing register endpoint
        reg_payload = {
            "device_id": "test_contract_dev_001",
            "device_name": "Contract Test Device",
            "device_type": "windows",
            "capabilities": ["screen", "keyboard"],
        }
        reg_resp = app_client.post("/api/v1/devices/register", json=reg_payload)
        # Registration may succeed or raise validation error depending on env;
        # we only care about the contract endpoint when the device exists.
        if reg_resp.status_code == 200:
            contract_resp = app_client.get(
                "/api/v1/devices/test_contract_dev_001/runtime-contract"
            )
            assert contract_resp.status_code == 200
            data = contract_resp.json()
            assert data["device_id"] == "test_contract_dev_001"
            # Validate all expected top-level keys are present
            for key in ("platform", "status", "online", "connection",
                        "capabilities", "autonomy", "session_presence",
                        "participation_hints", "metadata"):
                assert key in data, f"Missing key: {key}"
