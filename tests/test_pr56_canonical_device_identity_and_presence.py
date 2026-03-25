"""tests/test_pr56_canonical_device_identity_and_presence.py
=============================================================
Tests for PR-56: Canonical Device Identity and Runtime Presence Record
contracts.

Coverage:
  CanonicalDeviceIdentity
  1.  Default construction succeeds with only device_id.
  2.  All documented fields present in to_dict().
  3.  to_dict() is JSON-serialisable.
  4.  to_json() returns a valid JSON string.
  5.  from_dict() round-trip is stable.
  6.  device_id is preserved exactly.
  7.  platform defaults to 'unknown'.
  8.  capabilities list round-trips correctly.
  9.  supported_actions round-trips correctly.
  10. capability_schemas dict round-trips correctly.
  11. groups and tags round-trip correctly.
  12. supports_local_autonomy defaults to False.
  13. supports_remote_handoff defaults to False.
  14. has_capability() returns True for present cap.
  15. has_capability() returns False for absent cap.
  16. supports_action() returns True for present action.
  17. supports_action() returns False for absent action.
  18. metadata is preserved.
  19. No transport/WebSocket fields in to_dict().
  20. No connection_state or session_id fields in to_dict().

  from_registered_runtime_device adapter
  21. device_id is preserved.
  22. platform is extracted from platform enum.
  23. capabilities extracted from cap sub-object.
  24. supported_actions extracted from cap sub-object.
  25. autonomy.supports_local_autonomy propagated.
  26. autonomy.supports_remote_handoff propagated.
  27. participation_hints.groups propagated.
  28. participation_hints.tags propagated.
  29. metadata dict propagated.
  30. Graceful degradation on None input returns minimal identity.
  31. No transport fields leak through adapter.

  from_android_registration adapter
  32. device_id extracted from flat dict.
  33. platform extracted from 'platform' key.
  34. platform falls back to 'os' key.
  35. capabilities list extracted.
  36. supported_actions extracted.
  37. groups extracted.
  38. tags extracted.
  39. Extra keys stored in metadata.
  40. Graceful degradation on empty dict generates device_id.

  build_canonical_device_identity builder
  41. All keyword arguments map correctly.
  42. Default platform is 'unknown'.
  43. capabilities None defaults to empty list.
  44. supported_actions None defaults to empty list.
  45. metadata None defaults to empty dict.

  contracts package exports
  46. CanonicalDeviceIdentity importable from contracts package root.
  47. build_canonical_device_identity importable from contracts package root.
  48. canonical_identity_from_rrd importable from contracts package root.
  49. canonical_identity_from_android importable from contracts package root.

  RuntimePresenceRecord
  50. Default construction succeeds with only device_id.
  51. All documented fields present in to_dict().
  52. to_dict() is JSON-serialisable.
  53. to_json() returns valid JSON.
  54. from_dict() round-trip is stable.
  55. online defaults to False.
  56. transport defaults to 'unknown'.
  57. connection_state defaults to 'disconnected'.
  58. routable defaults to False.
  59. degraded defaults to False.
  60. pending_task_ids defaults to empty list.
  61. is_connected() True for connection_state='connected'.
  62. is_connected() False for other states.
  63. is_available_for_dispatch() True when online+routable+not degraded.
  64. is_available_for_dispatch() False when offline.
  65. is_available_for_dispatch() False when not routable.
  66. is_available_for_dispatch() False when degraded.
  67. seconds_since_seen() returns inf for last_seen==0.
  68. seconds_since_seen() returns non-negative for recent timestamp.
  69. No capability or platform fields in to_dict().
  70. current_task_id stored and retrieved.

  RuntimeTransport helper
  71. normalise('websocket') returns 'websocket'.
  72. normalise('ws') returns 'websocket'.
  73. normalise('wss') returns 'websocket'.
  74. normalise('http') returns 'http'.
  75. normalise('webrtc') returns 'webrtc'.
  76. normalise(None) returns 'unknown'.
  77. normalise('WEBSOCKET') returns 'websocket' (case-insensitive).

  from_registered_runtime_device adapter (presence)
  78. device_id preserved.
  79. online extracted.
  80. connection sub-object: transport extracted.
  81. connection sub-object: connection_state extracted.
  82. session_presence: current_task_id extracted.
  83. session_presence: pending_task_ids extracted.
  84. Graceful degradation on None input.

  build_runtime_presence_record builder
  85. All keyword arguments map correctly.
  86. transport normalised on construction.
  87. last_seen 0.0 when not provided.

  contracts package exports (presence)
  88. RuntimePresenceRecord importable from contracts package root.
  89. RuntimeTransport importable from contracts package root.
  90. build_runtime_presence_record importable from contracts package root.
  91. presence_record_from_rrd importable from contracts package root.
"""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers — mock objects
# ---------------------------------------------------------------------------

def _make_mock_rrd(
    *,
    device_id: str = "dev_rrd_001",
    device_name: str = "My Device",
    owner_id: str = "owner_1",
    platform: str = "android",
    device_type: str = "android_phone",
    form_factor: str = "phone",
    capabilities: list = None,
    supported_actions: list = None,
    capability_schemas: dict = None,
    supports_local_autonomy: bool = True,
    supports_remote_handoff: bool = False,
    groups: list = None,
    tags: list = None,
    metadata: dict = None,
    online: bool = True,
    status: str = "online",
    connection_id: str = "conn_001",
    session_id: str = "sess_001",
    transport: str = "websocket",
    connection_state: str = "connected",
    last_seen: float = None,
    current_task_id: str = None,
    pending_task_ids: list = None,
    active_session_ids: list = None,
) -> MagicMock:
    """Create a mock object shaped like RegisteredRuntimeDevice."""
    m = MagicMock()
    m.device_id = device_id
    m.device_name = device_name
    m.owner_id = owner_id

    # platform as mock enum
    plat_mock = MagicMock()
    plat_mock.value = platform
    m.platform = plat_mock

    m.device_type = device_type
    m.form_factor = form_factor
    m.online = online
    m.status = status
    m.metadata = dict(metadata or {})
    m.last_seen = last_seen if last_seen is not None else time.time()
    m.degraded = None  # explicit None → False

    # capabilities sub-object
    cap_mock = MagicMock()
    cap_mock.capabilities = list(capabilities or ["screen", "camera"])
    cap_mock.supported_actions = list(supported_actions or ["click", "type"])
    cap_mock.capability_schemas = dict(capability_schemas or {})
    m.capabilities = cap_mock

    # autonomy
    auto_mock = MagicMock()
    auto_mock.supports_local_autonomy = supports_local_autonomy
    auto_mock.supports_remote_handoff = supports_remote_handoff
    m.autonomy = auto_mock

    # participation hints
    hints_mock = MagicMock()
    hints_mock.groups = list(groups or ["g1"])
    hints_mock.tags = list(tags or ["tag_a"])
    m.participation_hints = hints_mock

    # connection sub-object
    conn_mock = MagicMock()
    conn_mock.connection_id = connection_id
    conn_mock.session_id = session_id
    transport_mock = MagicMock()
    transport_mock.value = transport
    conn_mock.transport = transport_mock
    conn_state_mock = MagicMock()
    conn_state_mock.value = connection_state
    conn_mock.connection_state = conn_state_mock
    m.connection = conn_mock

    # session presence
    sess_mock = MagicMock()
    sess_mock.current_task_id = current_task_id
    sess_mock.pending_task_ids = list(pending_task_ids or [])
    sess_mock.active_session_ids = list(active_session_ids or ["sess_001"])
    m.session_presence = sess_mock

    return m


# ===========================================================================
# CanonicalDeviceIdentity tests
# ===========================================================================

class TestCanonicalDeviceIdentityConstruction:
    """Tests 1–5: Basic construction and serialisation."""

    def test_01_default_construction_with_device_id_only(self):
        from contracts.canonical_device_identity import CanonicalDeviceIdentity
        identity = CanonicalDeviceIdentity(device_id="dev_001")
        assert identity.device_id == "dev_001"

    def test_02_all_documented_fields_in_to_dict(self):
        from contracts.canonical_device_identity import CanonicalDeviceIdentity
        identity = CanonicalDeviceIdentity(device_id="dev_001")
        d = identity.to_dict()
        expected_keys = {
            "device_id", "device_name", "owner_id",
            "platform", "device_type", "form_factor",
            "capabilities", "supported_actions", "capability_schemas",
            "supports_local_autonomy", "supports_remote_handoff",
            "groups", "tags", "metadata",
        }
        assert expected_keys <= set(d.keys())

    def test_03_to_dict_is_json_serialisable(self):
        from contracts.canonical_device_identity import build_canonical_device_identity
        identity = build_canonical_device_identity(
            device_id="dev_001",
            capabilities=["screen"],
            metadata={"model": "Pixel 7"},
        )
        d = identity.to_dict()
        # Should not raise
        json.dumps(d)

    def test_04_to_json_returns_valid_json(self):
        from contracts.canonical_device_identity import CanonicalDeviceIdentity
        identity = CanonicalDeviceIdentity(device_id="dev_001")
        s = identity.to_json()
        parsed = json.loads(s)
        assert parsed["device_id"] == "dev_001"

    def test_05_from_dict_round_trip_stable(self):
        from contracts.canonical_device_identity import build_canonical_device_identity
        identity = build_canonical_device_identity(
            device_id="dev_rt",
            platform="android",
            capabilities=["screen", "camera"],
            groups=["g1", "g2"],
        )
        d = identity.to_dict()
        from contracts.canonical_device_identity import CanonicalDeviceIdentity
        restored = CanonicalDeviceIdentity.from_dict(d)
        assert restored.device_id == identity.device_id
        assert restored.platform == identity.platform
        assert restored.capabilities == identity.capabilities
        assert restored.groups == identity.groups


class TestCanonicalDeviceIdentityFields:
    """Tests 6–20: Field values and constraints."""

    def test_06_device_id_preserved_exactly(self):
        from contracts.canonical_device_identity import CanonicalDeviceIdentity
        identity = CanonicalDeviceIdentity(device_id="abc-123-xyz")
        assert identity.device_id == "abc-123-xyz"

    def test_07_platform_defaults_to_unknown(self):
        from contracts.canonical_device_identity import CanonicalDeviceIdentity
        identity = CanonicalDeviceIdentity(device_id="dev_001")
        assert identity.platform == "unknown"

    def test_08_capabilities_round_trips(self):
        from contracts.canonical_device_identity import build_canonical_device_identity
        caps = ["screen", "camera", "microphone"]
        identity = build_canonical_device_identity(device_id="d", capabilities=caps)
        assert identity.capabilities == caps

    def test_09_supported_actions_round_trips(self):
        from contracts.canonical_device_identity import build_canonical_device_identity
        actions = ["click", "swipe", "type"]
        identity = build_canonical_device_identity(device_id="d", supported_actions=actions)
        assert identity.supported_actions == actions

    def test_10_capability_schemas_dict_round_trips(self):
        from contracts.canonical_device_identity import build_canonical_device_identity
        schemas = {"click": {"x": "int", "y": "int"}}
        identity = build_canonical_device_identity(device_id="d", capability_schemas=schemas)
        assert identity.capability_schemas == schemas

    def test_11_groups_and_tags_round_trip(self):
        from contracts.canonical_device_identity import build_canonical_device_identity
        identity = build_canonical_device_identity(
            device_id="d", groups=["team_a"], tags=["prod", "mobile"]
        )
        assert identity.groups == ["team_a"]
        assert identity.tags == ["prod", "mobile"]

    def test_12_supports_local_autonomy_default_false(self):
        from contracts.canonical_device_identity import CanonicalDeviceIdentity
        identity = CanonicalDeviceIdentity(device_id="d")
        assert identity.supports_local_autonomy is False

    def test_13_supports_remote_handoff_default_false(self):
        from contracts.canonical_device_identity import CanonicalDeviceIdentity
        identity = CanonicalDeviceIdentity(device_id="d")
        assert identity.supports_remote_handoff is False

    def test_14_has_capability_true_for_present_cap(self):
        from contracts.canonical_device_identity import build_canonical_device_identity
        identity = build_canonical_device_identity(device_id="d", capabilities=["screen"])
        assert identity.has_capability("screen") is True

    def test_15_has_capability_false_for_absent_cap(self):
        from contracts.canonical_device_identity import build_canonical_device_identity
        identity = build_canonical_device_identity(device_id="d", capabilities=["screen"])
        assert identity.has_capability("gps") is False

    def test_16_supports_action_true_for_present_action(self):
        from contracts.canonical_device_identity import build_canonical_device_identity
        identity = build_canonical_device_identity(device_id="d", supported_actions=["click"])
        assert identity.supports_action("click") is True

    def test_17_supports_action_false_for_absent_action(self):
        from contracts.canonical_device_identity import build_canonical_device_identity
        identity = build_canonical_device_identity(device_id="d", supported_actions=["click"])
        assert identity.supports_action("scroll") is False

    def test_18_metadata_preserved(self):
        from contracts.canonical_device_identity import build_canonical_device_identity
        meta = {"os_version": "Android 14", "model": "Pixel 7"}
        identity = build_canonical_device_identity(device_id="d", metadata=meta)
        assert identity.metadata == meta

    def test_19_no_transport_websocket_fields_in_to_dict(self):
        from contracts.canonical_device_identity import CanonicalDeviceIdentity
        identity = CanonicalDeviceIdentity(device_id="d")
        d = identity.to_dict()
        # Must not carry any transport/WebSocket fields
        forbidden = {"transport", "websocket", "ws_ref", "socket", "connection_id"}
        assert not forbidden.intersection(d.keys()), (
            f"Forbidden transport fields found: {forbidden.intersection(d.keys())}"
        )

    def test_20_no_connection_state_or_session_id_in_to_dict(self):
        from contracts.canonical_device_identity import CanonicalDeviceIdentity
        identity = CanonicalDeviceIdentity(device_id="d")
        d = identity.to_dict()
        # Must not carry ephemeral presence fields
        forbidden = {"connection_state", "session_id", "online", "last_seen"}
        assert not forbidden.intersection(d.keys()), (
            f"Forbidden presence fields found: {forbidden.intersection(d.keys())}"
        )


class TestCanonicalDeviceIdentityFromRRD:
    """Tests 21–31: from_registered_runtime_device adapter."""

    def test_21_device_id_preserved(self):
        from contracts.canonical_device_identity import from_registered_runtime_device
        rrd = _make_mock_rrd(device_id="rrd_dev_001")
        identity = from_registered_runtime_device(rrd)
        assert identity.device_id == "rrd_dev_001"

    def test_22_platform_extracted_from_enum(self):
        from contracts.canonical_device_identity import from_registered_runtime_device
        rrd = _make_mock_rrd(platform="android")
        identity = from_registered_runtime_device(rrd)
        assert identity.platform == "android"

    def test_23_capabilities_extracted_from_sub_object(self):
        from contracts.canonical_device_identity import from_registered_runtime_device
        rrd = _make_mock_rrd(capabilities=["screen", "camera", "gps"])
        identity = from_registered_runtime_device(rrd)
        assert "screen" in identity.capabilities
        assert "camera" in identity.capabilities

    def test_24_supported_actions_extracted(self):
        from contracts.canonical_device_identity import from_registered_runtime_device
        rrd = _make_mock_rrd(supported_actions=["click", "swipe"])
        identity = from_registered_runtime_device(rrd)
        assert "click" in identity.supported_actions

    def test_25_supports_local_autonomy_propagated(self):
        from contracts.canonical_device_identity import from_registered_runtime_device
        rrd = _make_mock_rrd(supports_local_autonomy=True)
        identity = from_registered_runtime_device(rrd)
        assert identity.supports_local_autonomy is True

    def test_26_supports_remote_handoff_propagated(self):
        from contracts.canonical_device_identity import from_registered_runtime_device
        rrd = _make_mock_rrd(supports_remote_handoff=True)
        identity = from_registered_runtime_device(rrd)
        assert identity.supports_remote_handoff is True

    def test_27_groups_propagated(self):
        from contracts.canonical_device_identity import from_registered_runtime_device
        rrd = _make_mock_rrd(groups=["team_alpha", "team_beta"])
        identity = from_registered_runtime_device(rrd)
        assert "team_alpha" in identity.groups

    def test_28_tags_propagated(self):
        from contracts.canonical_device_identity import from_registered_runtime_device
        rrd = _make_mock_rrd(tags=["prod", "high-priority"])
        identity = from_registered_runtime_device(rrd)
        assert "prod" in identity.tags

    def test_29_metadata_dict_propagated(self):
        from contracts.canonical_device_identity import from_registered_runtime_device
        rrd = _make_mock_rrd(metadata={"os_version": "14"})
        identity = from_registered_runtime_device(rrd)
        assert identity.metadata.get("os_version") == "14"

    def test_30_graceful_degradation_on_none(self):
        from contracts.canonical_device_identity import from_registered_runtime_device
        result = from_registered_runtime_device(None)
        assert isinstance(result.device_id, str)
        assert len(result.device_id) > 0

    def test_31_no_transport_fields_leak_through_adapter(self):
        from contracts.canonical_device_identity import from_registered_runtime_device
        rrd = _make_mock_rrd()
        identity = from_registered_runtime_device(rrd)
        d = identity.to_dict()
        forbidden = {"transport", "connection_id", "websocket", "connection_state"}
        assert not forbidden.intersection(d.keys())


class TestCanonicalDeviceIdentityFromAndroid:
    """Tests 32–40: from_android_registration adapter."""

    def test_32_device_id_extracted(self):
        from contracts.canonical_device_identity import from_android_registration
        data = {"device_id": "android_001", "platform": "android"}
        identity = from_android_registration(data)
        assert identity.device_id == "android_001"

    def test_33_platform_from_platform_key(self):
        from contracts.canonical_device_identity import from_android_registration
        data = {"device_id": "d", "platform": "android"}
        identity = from_android_registration(data)
        assert identity.platform == "android"

    def test_34_platform_falls_back_to_os_key(self):
        from contracts.canonical_device_identity import from_android_registration
        data = {"device_id": "d", "os": "android"}
        identity = from_android_registration(data)
        assert identity.platform == "android"

    def test_35_capabilities_list_extracted(self):
        from contracts.canonical_device_identity import from_android_registration
        data = {"device_id": "d", "capabilities": ["screen", "camera"]}
        identity = from_android_registration(data)
        assert "screen" in identity.capabilities

    def test_36_supported_actions_extracted(self):
        from contracts.canonical_device_identity import from_android_registration
        data = {"device_id": "d", "supported_actions": ["click"]}
        identity = from_android_registration(data)
        assert "click" in identity.supported_actions

    def test_37_groups_extracted(self):
        from contracts.canonical_device_identity import from_android_registration
        data = {"device_id": "d", "groups": ["formation_a"]}
        identity = from_android_registration(data)
        assert "formation_a" in identity.groups

    def test_38_tags_extracted(self):
        from contracts.canonical_device_identity import from_android_registration
        data = {"device_id": "d", "tags": ["primary"]}
        identity = from_android_registration(data)
        assert "primary" in identity.tags

    def test_39_extra_keys_stored_in_metadata(self):
        from contracts.canonical_device_identity import from_android_registration
        data = {"device_id": "d", "model": "Pixel 7", "os_version": "14"}
        identity = from_android_registration(data)
        assert identity.metadata.get("model") == "Pixel 7"

    def test_40_graceful_degradation_on_empty_dict(self):
        from contracts.canonical_device_identity import from_android_registration
        identity = from_android_registration({})
        assert isinstance(identity.device_id, str)
        assert len(identity.device_id) > 0


class TestCanonicalDeviceIdentityBuilder:
    """Tests 41–45: build_canonical_device_identity builder."""

    def test_41_all_kwargs_map_correctly(self):
        from contracts.canonical_device_identity import build_canonical_device_identity
        identity = build_canonical_device_identity(
            device_id="dev_kw",
            device_name="KW Device",
            owner_id="owner_kw",
            platform="windows",
            device_type="windows_desktop",
            form_factor="desktop",
            capabilities=["screen"],
            supported_actions=["click"],
            capability_schemas={"click": {}},
            supports_local_autonomy=True,
            supports_remote_handoff=True,
            groups=["g1"],
            tags=["t1"],
            metadata={"key": "val"},
        )
        assert identity.device_id == "dev_kw"
        assert identity.device_name == "KW Device"
        assert identity.owner_id == "owner_kw"
        assert identity.platform == "windows"
        assert identity.form_factor == "desktop"
        assert identity.supports_local_autonomy is True
        assert identity.supports_remote_handoff is True
        assert identity.metadata == {"key": "val"}

    def test_42_default_platform_is_unknown(self):
        from contracts.canonical_device_identity import build_canonical_device_identity
        identity = build_canonical_device_identity(device_id="d")
        assert identity.platform == "unknown"

    def test_43_capabilities_none_defaults_to_empty_list(self):
        from contracts.canonical_device_identity import build_canonical_device_identity
        identity = build_canonical_device_identity(device_id="d", capabilities=None)
        assert identity.capabilities == []

    def test_44_supported_actions_none_defaults_empty(self):
        from contracts.canonical_device_identity import build_canonical_device_identity
        identity = build_canonical_device_identity(device_id="d", supported_actions=None)
        assert identity.supported_actions == []

    def test_45_metadata_none_defaults_to_empty_dict(self):
        from contracts.canonical_device_identity import build_canonical_device_identity
        identity = build_canonical_device_identity(device_id="d", metadata=None)
        assert identity.metadata == {}


class TestCanonicalDeviceIdentityContractsExports:
    """Tests 46–49: contracts package root exports."""

    def test_46_canonical_device_identity_importable_from_contracts(self):
        from contracts import CanonicalDeviceIdentity
        assert CanonicalDeviceIdentity is not None

    def test_47_build_canonical_device_identity_importable(self):
        from contracts import build_canonical_device_identity
        assert callable(build_canonical_device_identity)

    def test_48_canonical_identity_from_rrd_importable(self):
        from contracts import canonical_identity_from_rrd
        assert callable(canonical_identity_from_rrd)

    def test_49_canonical_identity_from_android_importable(self):
        from contracts import canonical_identity_from_android
        assert callable(canonical_identity_from_android)


# ===========================================================================
# RuntimePresenceRecord tests
# ===========================================================================

class TestRuntimePresenceRecordConstruction:
    """Tests 50–54: Basic construction and serialisation."""

    def test_50_default_construction_with_device_id_only(self):
        from contracts.runtime_presence_record import RuntimePresenceRecord
        record = RuntimePresenceRecord(device_id="dev_001")
        assert record.device_id == "dev_001"

    def test_51_all_documented_fields_in_to_dict(self):
        from contracts.runtime_presence_record import RuntimePresenceRecord
        record = RuntimePresenceRecord(device_id="dev_001")
        d = record.to_dict()
        expected_keys = {
            "device_id", "connection_id", "session_id",
            "transport", "connection_state",
            "online", "last_seen",
            "routable", "degraded",
            "current_task_id", "pending_task_ids",
        }
        assert expected_keys <= set(d.keys())

    def test_52_to_dict_is_json_serialisable(self):
        from contracts.runtime_presence_record import build_runtime_presence_record
        record = build_runtime_presence_record(
            device_id="dev_001",
            online=True,
            last_seen=time.time(),
        )
        json.dumps(record.to_dict())

    def test_53_to_json_returns_valid_json(self):
        from contracts.runtime_presence_record import RuntimePresenceRecord
        record = RuntimePresenceRecord(device_id="dev_001")
        s = record.to_json()
        parsed = json.loads(s)
        assert parsed["device_id"] == "dev_001"

    def test_54_from_dict_round_trip_stable(self):
        from contracts.runtime_presence_record import build_runtime_presence_record, RuntimePresenceRecord
        record = build_runtime_presence_record(
            device_id="dev_rt",
            online=True,
            transport="websocket",
            connection_state="connected",
            routable=True,
        )
        d = record.to_dict()
        restored = RuntimePresenceRecord.from_dict(d)
        assert restored.device_id == record.device_id
        assert restored.online == record.online
        assert restored.transport == record.transport
        assert restored.routable == record.routable


class TestRuntimePresenceRecordDefaults:
    """Tests 55–70: Default values and field constraints."""

    def test_55_online_defaults_false(self):
        from contracts.runtime_presence_record import RuntimePresenceRecord
        record = RuntimePresenceRecord(device_id="d")
        assert record.online is False

    def test_56_transport_defaults_unknown(self):
        from contracts.runtime_presence_record import RuntimePresenceRecord
        record = RuntimePresenceRecord(device_id="d")
        assert record.transport == "unknown"

    def test_57_connection_state_defaults_disconnected(self):
        from contracts.runtime_presence_record import RuntimePresenceRecord
        record = RuntimePresenceRecord(device_id="d")
        assert record.connection_state == "disconnected"

    def test_58_routable_defaults_false(self):
        from contracts.runtime_presence_record import RuntimePresenceRecord
        record = RuntimePresenceRecord(device_id="d")
        assert record.routable is False

    def test_59_degraded_defaults_false(self):
        from contracts.runtime_presence_record import RuntimePresenceRecord
        record = RuntimePresenceRecord(device_id="d")
        assert record.degraded is False

    def test_60_pending_task_ids_defaults_empty_list(self):
        from contracts.runtime_presence_record import RuntimePresenceRecord
        record = RuntimePresenceRecord(device_id="d")
        assert record.pending_task_ids == []

    def test_61_is_connected_true_when_state_connected(self):
        from contracts.runtime_presence_record import RuntimePresenceRecord
        record = RuntimePresenceRecord(device_id="d", connection_state="connected")
        assert record.is_connected() is True

    def test_62_is_connected_false_for_other_states(self):
        from contracts.runtime_presence_record import RuntimePresenceRecord
        for state in ("disconnected", "connecting", "reconnecting", "disconnecting"):
            record = RuntimePresenceRecord(device_id="d", connection_state=state)
            assert record.is_connected() is False

    def test_63_is_available_for_dispatch_true_all_conditions(self):
        from contracts.runtime_presence_record import build_runtime_presence_record
        record = build_runtime_presence_record(
            device_id="d", online=True, routable=True, degraded=False
        )
        assert record.is_available_for_dispatch() is True

    def test_64_is_available_for_dispatch_false_when_offline(self):
        from contracts.runtime_presence_record import build_runtime_presence_record
        record = build_runtime_presence_record(
            device_id="d", online=False, routable=True, degraded=False
        )
        assert record.is_available_for_dispatch() is False

    def test_65_is_available_for_dispatch_false_when_not_routable(self):
        from contracts.runtime_presence_record import build_runtime_presence_record
        record = build_runtime_presence_record(
            device_id="d", online=True, routable=False, degraded=False
        )
        assert record.is_available_for_dispatch() is False

    def test_66_is_available_for_dispatch_false_when_degraded(self):
        from contracts.runtime_presence_record import build_runtime_presence_record
        record = build_runtime_presence_record(
            device_id="d", online=True, routable=True, degraded=True
        )
        assert record.is_available_for_dispatch() is False

    def test_67_seconds_since_seen_inf_for_zero_last_seen(self):
        from contracts.runtime_presence_record import RuntimePresenceRecord
        import math
        record = RuntimePresenceRecord(device_id="d", last_seen=0.0)
        assert math.isinf(record.seconds_since_seen())

    def test_68_seconds_since_seen_non_negative_for_recent(self):
        from contracts.runtime_presence_record import RuntimePresenceRecord
        record = RuntimePresenceRecord(device_id="d", last_seen=time.time())
        assert record.seconds_since_seen() >= 0

    def test_69_no_capability_or_platform_fields_in_to_dict(self):
        from contracts.runtime_presence_record import RuntimePresenceRecord
        record = RuntimePresenceRecord(device_id="d")
        d = record.to_dict()
        forbidden = {"capabilities", "platform", "supported_actions", "device_type"}
        assert not forbidden.intersection(d.keys())

    def test_70_current_task_id_stored_and_retrieved(self):
        from contracts.runtime_presence_record import build_runtime_presence_record
        record = build_runtime_presence_record(
            device_id="d", current_task_id="task_xyz"
        )
        assert record.current_task_id == "task_xyz"


class TestRuntimeTransport:
    """Tests 71–77: RuntimeTransport helper."""

    def test_71_normalise_websocket(self):
        from contracts.runtime_presence_record import RuntimeTransport
        assert RuntimeTransport.normalise("websocket") == "websocket"

    def test_72_normalise_ws_alias(self):
        from contracts.runtime_presence_record import RuntimeTransport
        assert RuntimeTransport.normalise("ws") == "websocket"

    def test_73_normalise_wss_alias(self):
        from contracts.runtime_presence_record import RuntimeTransport
        assert RuntimeTransport.normalise("wss") == "websocket"

    def test_74_normalise_http(self):
        from contracts.runtime_presence_record import RuntimeTransport
        assert RuntimeTransport.normalise("http") == "http"

    def test_75_normalise_webrtc(self):
        from contracts.runtime_presence_record import RuntimeTransport
        assert RuntimeTransport.normalise("webrtc") == "webrtc"

    def test_76_normalise_none_returns_unknown(self):
        from contracts.runtime_presence_record import RuntimeTransport
        assert RuntimeTransport.normalise(None) == "unknown"

    def test_77_normalise_case_insensitive(self):
        from contracts.runtime_presence_record import RuntimeTransport
        assert RuntimeTransport.normalise("WEBSOCKET") == "websocket"


class TestRuntimePresenceRecordFromRRD:
    """Tests 78–84: from_registered_runtime_device (presence) adapter."""

    def test_78_device_id_preserved(self):
        from contracts.runtime_presence_record import from_registered_runtime_device
        rrd = _make_mock_rrd(device_id="presence_dev")
        record = from_registered_runtime_device(rrd)
        assert record.device_id == "presence_dev"

    def test_79_online_extracted(self):
        from contracts.runtime_presence_record import from_registered_runtime_device
        rrd = _make_mock_rrd(online=True)
        record = from_registered_runtime_device(rrd)
        assert record.online is True

    def test_80_transport_extracted_from_connection(self):
        from contracts.runtime_presence_record import from_registered_runtime_device
        rrd = _make_mock_rrd(transport="websocket")
        record = from_registered_runtime_device(rrd)
        assert record.transport == "websocket"

    def test_81_connection_state_extracted(self):
        from contracts.runtime_presence_record import from_registered_runtime_device
        rrd = _make_mock_rrd(connection_state="connected")
        record = from_registered_runtime_device(rrd)
        assert record.connection_state == "connected"

    def test_82_current_task_id_extracted(self):
        from contracts.runtime_presence_record import from_registered_runtime_device
        rrd = _make_mock_rrd(current_task_id="task_001")
        record = from_registered_runtime_device(rrd)
        assert record.current_task_id == "task_001"

    def test_83_pending_task_ids_extracted(self):
        from contracts.runtime_presence_record import from_registered_runtime_device
        rrd = _make_mock_rrd(pending_task_ids=["t1", "t2"])
        record = from_registered_runtime_device(rrd)
        assert "t1" in record.pending_task_ids
        assert "t2" in record.pending_task_ids

    def test_84_graceful_degradation_on_none(self):
        from contracts.runtime_presence_record import from_registered_runtime_device
        result = from_registered_runtime_device(None)
        assert isinstance(result.device_id, str)
        assert len(result.device_id) > 0


class TestBuildRuntimePresenceRecordBuilder:
    """Tests 85–87: build_runtime_presence_record builder."""

    def test_85_all_kwargs_map_correctly(self):
        from contracts.runtime_presence_record import build_runtime_presence_record
        record = build_runtime_presence_record(
            device_id="bld_dev",
            connection_id="conn_bld",
            session_id="sess_bld",
            transport="websocket",
            connection_state="connected",
            online=True,
            last_seen=12345.0,
            routable=True,
            degraded=False,
            current_task_id="task_bld",
            pending_task_ids=["t1"],
        )
        assert record.device_id == "bld_dev"
        assert record.connection_id == "conn_bld"
        assert record.session_id == "sess_bld"
        assert record.transport == "websocket"
        assert record.connection_state == "connected"
        assert record.online is True
        assert record.last_seen == 12345.0
        assert record.routable is True
        assert record.degraded is False
        assert record.current_task_id == "task_bld"
        assert "t1" in record.pending_task_ids

    def test_86_transport_normalised_on_construction(self):
        from contracts.runtime_presence_record import build_runtime_presence_record
        record = build_runtime_presence_record(device_id="d", transport="ws")
        assert record.transport == "websocket"

    def test_87_last_seen_zero_when_not_provided(self):
        from contracts.runtime_presence_record import build_runtime_presence_record
        record = build_runtime_presence_record(device_id="d")
        assert record.last_seen == 0.0


class TestRuntimePresenceRecordContractsExports:
    """Tests 88–91: contracts package root exports (presence)."""

    def test_88_runtime_presence_record_importable(self):
        from contracts import RuntimePresenceRecord
        assert RuntimePresenceRecord is not None

    def test_89_runtime_transport_importable(self):
        from contracts import RuntimeTransport
        assert RuntimeTransport is not None

    def test_90_build_runtime_presence_record_importable(self):
        from contracts import build_runtime_presence_record
        assert callable(build_runtime_presence_record)

    def test_91_presence_record_from_rrd_importable(self):
        from contracts import presence_record_from_rrd
        assert callable(presence_record_from_rrd)
