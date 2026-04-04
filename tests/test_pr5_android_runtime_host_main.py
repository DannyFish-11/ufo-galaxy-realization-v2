"""tests/test_pr5_android_runtime_host_main.py
===============================================
Tests for PR-5 (main-repo half): Android as a first-class runtime host.

Post-533 dual-repo unification track — this is the MAIN-repo side of PR-5.

Coverage:
  1. AndroidRuntimeHostRole classification (classify_android_runtime_host).
  2. AndroidRuntimeHostIdentity construction and serialisation.
  3. RegisteredRuntimeDevice carries source_runtime_posture + is_runtime_host.
  4. from_android_registration() populates posture and is_runtime_host correctly.
  5. LocalRuntimeHost carries source_runtime_posture propagated from device.
  6. RuntimeProjectionDeviceEntry carries source_runtime_posture + is_runtime_host.
  7. RuntimeProjectionHostEntry carries source_runtime_posture.
  8. project_runtime_devices() propagates posture from device dicts.
  9. project_runtime_hosts() propagates posture from host dicts.
  10. Policy sentinels are present.
  11. Backwards-compatibility: existing fields unaffected; defaults are safe.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _android_payload(**kw: Any) -> dict:
    """Standard Android registration payload dict."""
    return {
        "device_id": kw.get("device_id", "android_ph_001"),
        "name": kw.get("name", "Pixel 9"),
        "model": kw.get("model", "Pixel 9"),
        "os_version": kw.get("os_version", "15"),
        "sdk_version": kw.get("sdk_version", 35),
        "capabilities": kw.get("capabilities", ["screen", "camera"]),
        "app_version": kw.get("app_version", "3.2.0"),
        "device_type": kw.get("device_type", "android_phone"),
        "source_runtime_posture": kw.get("source_runtime_posture", "join_runtime"),
    }


def _android_payload_control_only(**kw: Any) -> dict:
    """Android payload without explicit join posture (legacy / control-only)."""
    p = _android_payload(**kw)
    p["source_runtime_posture"] = "control_only"
    return p


def _android_payload_no_posture(**kw: Any) -> dict:
    """Android payload without any source_runtime_posture field (very legacy)."""
    p = _android_payload(**kw)
    p.pop("source_runtime_posture", None)
    return p


def _mock_registered_device(
    device_id: str = "android_001",
    source_runtime_posture: str = "join_runtime",
    is_runtime_host: bool = True,
    runtime_enabled: bool = True,
    supports_remote_handoff: bool = True,
    online: bool = True,
    platform: str = "android",
    runtime_version: str = "3.2.0",
) -> MagicMock:
    """Mock a RegisteredRuntimeDevice with posture fields."""
    m = MagicMock()
    m.device_id = device_id
    m.device_name = "Mock Android"
    m.source_runtime_posture = source_runtime_posture
    m.is_runtime_host = is_runtime_host
    m.platform = platform
    m.online = online
    autonomy = MagicMock()
    autonomy.runtime_enabled = runtime_enabled
    autonomy.supports_remote_handoff = supports_remote_handoff
    autonomy.runtime_version = runtime_version
    autonomy.runtime_id = None
    autonomy.supports_local_autonomy = False
    m.autonomy = autonomy
    m.status = "online"
    session_presence = MagicMock()
    session_presence.active_session_ids = []
    m.session_presence = session_presence
    capabilities = MagicMock()
    capabilities.capabilities = ["screen", "camera"]
    m.capabilities = capabilities
    m.participation_hints = MagicMock()
    m.participation_hints.preferred_callback_channel = ""
    m.metadata = {}
    return m


# ---------------------------------------------------------------------------
# 1. AndroidRuntimeHostRole classification
# ---------------------------------------------------------------------------

class TestClassifyAndroidRuntimeHostRole:
    """classify_android_runtime_host() returns the correct role."""

    def test_join_runtime_posture_yields_full_host(self):
        from core.android_runtime_host import classify_android_runtime_host, AndroidRuntimeHostRole
        device = _mock_registered_device(source_runtime_posture="join_runtime", is_runtime_host=True)
        role = classify_android_runtime_host(device)
        assert role == AndroidRuntimeHostRole.FULL_RUNTIME_HOST

    def test_join_runtime_posture_alone_yields_full_host(self):
        """join_runtime posture is sufficient even without is_runtime_host flag."""
        from core.android_runtime_host import classify_android_runtime_host, AndroidRuntimeHostRole
        device = _mock_registered_device(source_runtime_posture="join_runtime", is_runtime_host=False)
        role = classify_android_runtime_host(device)
        assert role == AndroidRuntimeHostRole.FULL_RUNTIME_HOST

    def test_is_runtime_host_without_join_posture_yields_partial(self):
        from core.android_runtime_host import classify_android_runtime_host, AndroidRuntimeHostRole
        device = _mock_registered_device(
            source_runtime_posture="control_only",
            is_runtime_host=True,
            runtime_enabled=True,
            supports_remote_handoff=True,
        )
        role = classify_android_runtime_host(device)
        assert role == AndroidRuntimeHostRole.PARTIAL_RUNTIME_HOST

    def test_autonomy_flags_without_posture_yields_partial(self):
        from core.android_runtime_host import classify_android_runtime_host, AndroidRuntimeHostRole
        device = _mock_registered_device(
            source_runtime_posture="control_only",
            is_runtime_host=False,
            runtime_enabled=True,
            supports_remote_handoff=True,
        )
        role = classify_android_runtime_host(device)
        assert role == AndroidRuntimeHostRole.PARTIAL_RUNTIME_HOST

    def test_online_no_runtime_yields_connected_device_only(self):
        from core.android_runtime_host import classify_android_runtime_host, AndroidRuntimeHostRole
        device = _mock_registered_device(
            source_runtime_posture="control_only",
            is_runtime_host=False,
            runtime_enabled=False,
            supports_remote_handoff=False,
            online=True,
        )
        role = classify_android_runtime_host(device)
        assert role == AndroidRuntimeHostRole.CONNECTED_DEVICE_ONLY

    def test_offline_no_signals_yields_unclassified(self):
        from core.android_runtime_host import classify_android_runtime_host, AndroidRuntimeHostRole
        device = _mock_registered_device(
            source_runtime_posture="control_only",
            is_runtime_host=False,
            runtime_enabled=False,
            supports_remote_handoff=False,
            online=False,
        )
        role = classify_android_runtime_host(device)
        assert role == AndroidRuntimeHostRole.UNCLASSIFIED

    def test_dict_input_join_runtime(self):
        """classify_android_runtime_host() works with a plain dict."""
        from core.android_runtime_host import classify_android_runtime_host, AndroidRuntimeHostRole
        d = {
            "device_id": "ph_dict",
            "source_runtime_posture": "join_runtime",
            "is_runtime_host": True,
            "online": True,
            "autonomy": {"runtime_enabled": True, "supports_remote_handoff": True},
        }
        role = classify_android_runtime_host(d)
        assert role == AndroidRuntimeHostRole.FULL_RUNTIME_HOST

    def test_dict_input_control_only_online(self):
        from core.android_runtime_host import classify_android_runtime_host, AndroidRuntimeHostRole
        d = {
            "device_id": "ph_dict_ctrl",
            "source_runtime_posture": "control_only",
            "is_runtime_host": False,
            "online": True,
            "autonomy": {"runtime_enabled": False, "supports_remote_handoff": False},
        }
        role = classify_android_runtime_host(d)
        assert role == AndroidRuntimeHostRole.CONNECTED_DEVICE_ONLY

    def test_broken_object_returns_unclassified(self):
        from core.android_runtime_host import classify_android_runtime_host, AndroidRuntimeHostRole
        class Broken:
            @property
            def source_runtime_posture(self):
                raise RuntimeError("broken")
        role = classify_android_runtime_host(Broken())
        assert role == AndroidRuntimeHostRole.UNCLASSIFIED


# ---------------------------------------------------------------------------
# 2. AndroidRuntimeHostIdentity construction and serialisation
# ---------------------------------------------------------------------------

class TestAndroidRuntimeHostIdentity:
    """AndroidRuntimeHostIdentity is constructed and serialises correctly."""

    def test_build_from_join_runtime_device(self):
        from core.android_runtime_host import (
            build_android_runtime_host_identity,
            AndroidRuntimeHostRole,
        )
        device = _mock_registered_device(source_runtime_posture="join_runtime", is_runtime_host=True)
        identity = build_android_runtime_host_identity(device)
        assert identity.device_id == "android_001"
        assert identity.role == AndroidRuntimeHostRole.FULL_RUNTIME_HOST
        assert identity.source_runtime_posture == "join_runtime"
        assert identity.is_runtime_host is True
        assert identity.formation_eligible is True

    def test_build_from_connected_device_only(self):
        from core.android_runtime_host import (
            build_android_runtime_host_identity,
            AndroidRuntimeHostRole,
        )
        device = _mock_registered_device(
            source_runtime_posture="control_only",
            is_runtime_host=False,
            runtime_enabled=False,
            supports_remote_handoff=False,
            online=True,
        )
        identity = build_android_runtime_host_identity(device)
        assert identity.role == AndroidRuntimeHostRole.CONNECTED_DEVICE_ONLY
        assert identity.formation_eligible is False

    def test_to_dict_stable_keys(self):
        from core.android_runtime_host import build_android_runtime_host_identity
        device = _mock_registered_device()
        d = build_android_runtime_host_identity(device).to_dict()
        required = {
            "snapshot_id", "device_id", "device_name", "role",
            "source_runtime_posture", "is_runtime_host",
            "runtime_enabled", "supports_remote_handoff",
            "runtime_version", "formation_eligible",
        }
        assert required <= set(d.keys()), f"Missing keys: {required - set(d.keys())}"

    def test_to_json_round_trip(self):
        from core.android_runtime_host import (
            build_android_runtime_host_identity,
            AndroidRuntimeHostIdentity,
        )
        device = _mock_registered_device()
        identity = build_android_runtime_host_identity(device)
        raw = identity.to_json()
        data = json.loads(raw)
        restored = AndroidRuntimeHostIdentity.from_dict(data)
        assert restored.device_id == identity.device_id
        assert restored.role == identity.role
        assert restored.source_runtime_posture == identity.source_runtime_posture
        assert restored.formation_eligible == identity.formation_eligible

    def test_snapshot_id_is_stable_string(self):
        from core.android_runtime_host import build_android_runtime_host_identity
        device = _mock_registered_device()
        identity = build_android_runtime_host_identity(device)
        assert identity.snapshot_id.startswith("arhi_")

    def test_build_from_dict(self):
        from core.android_runtime_host import (
            build_android_runtime_host_identity,
            AndroidRuntimeHostRole,
        )
        d = {
            "device_id": "ph_direct",
            "device_name": "Direct Phone",
            "source_runtime_posture": "join_runtime",
            "is_runtime_host": True,
            "online": True,
            "autonomy": {
                "runtime_enabled": True,
                "supports_remote_handoff": True,
                "runtime_version": "3.0.0",
            },
        }
        identity = build_android_runtime_host_identity(d)
        assert identity.device_id == "ph_direct"
        assert identity.role == AndroidRuntimeHostRole.FULL_RUNTIME_HOST
        assert identity.runtime_version == "3.0.0"

    def test_broken_device_returns_fallback(self):
        from core.android_runtime_host import build_android_runtime_host_identity
        class Broken:
            @property
            def device_id(self):
                raise RuntimeError("broken")
        identity = build_android_runtime_host_identity(Broken())
        assert identity.device_id.startswith("android_")


# ---------------------------------------------------------------------------
# 3. RegisteredRuntimeDevice carries source_runtime_posture + is_runtime_host
# ---------------------------------------------------------------------------

class TestRegisteredRuntimeDevicePostureFields:
    """RegisteredRuntimeDevice carries the new PR-5 posture fields."""

    def test_default_posture_is_control_only(self):
        from contracts.registered_runtime_device import RegisteredRuntimeDevice
        d = RegisteredRuntimeDevice(device_id="default_01")
        assert d.source_runtime_posture == "control_only"
        assert d.is_runtime_host is False

    def test_explicit_join_runtime_posture(self):
        from contracts.registered_runtime_device import RegisteredRuntimeDevice
        d = RegisteredRuntimeDevice(
            device_id="join_01",
            source_runtime_posture="join_runtime",
            is_runtime_host=True,
        )
        assert d.source_runtime_posture == "join_runtime"
        assert d.is_runtime_host is True

    def test_serialised_dict_carries_posture(self):
        from contracts.registered_runtime_device import RegisteredRuntimeDevice
        d = RegisteredRuntimeDevice(
            device_id="ser_01",
            source_runtime_posture="join_runtime",
            is_runtime_host=True,
        ).to_dict()
        assert d["source_runtime_posture"] == "join_runtime"
        assert d["is_runtime_host"] is True

    def test_round_trip_preserves_posture(self):
        from contracts.registered_runtime_device import RegisteredRuntimeDevice
        orig = RegisteredRuntimeDevice(
            device_id="rt_01",
            source_runtime_posture="join_runtime",
            is_runtime_host=True,
        )
        restored = RegisteredRuntimeDevice.from_dict(orig.to_dict())
        assert restored.source_runtime_posture == "join_runtime"
        assert restored.is_runtime_host is True

    def test_build_builder_accepts_posture(self):
        from contracts.registered_runtime_device import build_registered_runtime_device
        d = build_registered_runtime_device(
            device_id="builder_01",
            source_runtime_posture="join_runtime",
            is_runtime_host=True,
        )
        assert d.source_runtime_posture == "join_runtime"
        assert d.is_runtime_host is True

    def test_build_builder_defaults_safe(self):
        from contracts.registered_runtime_device import build_registered_runtime_device
        d = build_registered_runtime_device(device_id="builder_safe")
        assert d.source_runtime_posture == "control_only"
        assert d.is_runtime_host is False


# ---------------------------------------------------------------------------
# 4. from_android_registration() populates posture and is_runtime_host
# ---------------------------------------------------------------------------

class TestAndroidRegistrationPosturePopulation:
    """from_android_registration() sets posture and runtime-host flag."""

    def test_join_runtime_posture_in_payload(self):
        from contracts.registered_runtime_device import from_android_registration
        c = from_android_registration(_android_payload(source_runtime_posture="join_runtime"))
        assert c.source_runtime_posture == "join_runtime"
        assert c.is_runtime_host is True

    def test_control_only_posture_in_payload(self):
        from contracts.registered_runtime_device import from_android_registration
        c = from_android_registration(_android_payload_control_only())
        assert c.source_runtime_posture == "control_only"
        # still is_runtime_host=True because app_version is set (Galaxy app present)
        assert c.is_runtime_host is True

    def test_no_posture_field_defaults_to_control_only(self):
        from contracts.registered_runtime_device import from_android_registration
        c = from_android_registration(_android_payload_no_posture())
        assert c.source_runtime_posture == "control_only"

    def test_no_app_version_and_no_join_posture_not_runtime_host(self):
        """Without app_version AND without join posture → not a runtime host."""
        from contracts.registered_runtime_device import from_android_registration
        payload = {
            "device_id": "bare_android",
            "name": "Bare Android",
            "capabilities": ["screen"],
            # no source_runtime_posture, no app_version
        }
        c = from_android_registration(payload)
        assert c.source_runtime_posture == "control_only"
        assert c.is_runtime_host is False

    def test_unknown_posture_value_falls_back_to_control_only(self):
        from contracts.registered_runtime_device import from_android_registration
        payload = _android_payload(source_runtime_posture="some_future_value")
        c = from_android_registration(payload)
        assert c.source_runtime_posture == "control_only"

    def test_platform_is_android(self):
        from contracts.registered_runtime_device import from_android_registration, RuntimeDevicePlatform
        c = from_android_registration(_android_payload())
        assert c.platform in (RuntimeDevicePlatform.ANDROID, "android")

    def test_existing_fields_unaffected(self):
        """Existing contract fields (device_name, capabilities, etc.) still populate."""
        from contracts.registered_runtime_device import from_android_registration
        c = from_android_registration(_android_payload(
            name="My Pixel",
            capabilities=["screen", "gps"],
            app_version="3.5.0",
        ))
        assert c.device_name == "My Pixel"
        assert "screen" in c.capabilities.capabilities
        assert c.autonomy.runtime_version == "3.5.0"


# ---------------------------------------------------------------------------
# 5. LocalRuntimeHost carries source_runtime_posture
# ---------------------------------------------------------------------------

class TestLocalRuntimeHostPosturePropagation:
    """LocalRuntimeHost.source_runtime_posture is propagated from device."""

    def test_default_posture_is_control_only(self):
        from contracts.local_runtime_host import LocalRuntimeHost
        h = LocalRuntimeHost(device_id="lrh_default")
        assert h.source_runtime_posture == "control_only"

    def test_explicit_join_runtime_posture(self):
        from contracts.local_runtime_host import LocalRuntimeHost
        h = LocalRuntimeHost(device_id="lrh_join", source_runtime_posture="join_runtime")
        assert h.source_runtime_posture == "join_runtime"

    def test_from_registered_device_propagates_posture(self):
        from contracts.local_runtime_host import from_registered_runtime_device
        device = _mock_registered_device(source_runtime_posture="join_runtime")
        host = from_registered_runtime_device(device)
        assert host.source_runtime_posture == "join_runtime"

    def test_from_registered_device_control_only_preserves(self):
        from contracts.local_runtime_host import from_registered_runtime_device
        device = _mock_registered_device(source_runtime_posture="control_only")
        host = from_registered_runtime_device(device)
        assert host.source_runtime_posture == "control_only"

    def test_serialised_dict_carries_posture(self):
        from contracts.local_runtime_host import from_registered_runtime_device
        device = _mock_registered_device(source_runtime_posture="join_runtime")
        host = from_registered_runtime_device(device)
        d = host.to_dict()
        assert d["source_runtime_posture"] == "join_runtime"

    def test_sentinel_present(self):
        from contracts.local_runtime_host import LOCAL_RUNTIME_HOST_POSTURE_AWARE_PR5
        assert LOCAL_RUNTIME_HOST_POSTURE_AWARE_PR5 == "LOCAL_RUNTIME_HOST_POSTURE_AWARE_PR5"


# ---------------------------------------------------------------------------
# 6. RuntimeProjectionDeviceEntry carries posture + is_runtime_host
# ---------------------------------------------------------------------------

class TestRuntimeProjectionDeviceEntryPosture:
    """RuntimeProjectionDeviceEntry carries source_runtime_posture and is_runtime_host."""

    def test_default_values(self):
        from contracts.multi_device_runtime_projection import RuntimeProjectionDeviceEntry
        e = RuntimeProjectionDeviceEntry(device_id="entry_default")
        assert e.source_runtime_posture == "control_only"
        assert e.is_runtime_host is False

    def test_explicit_posture_and_host_flag(self):
        from contracts.multi_device_runtime_projection import RuntimeProjectionDeviceEntry
        e = RuntimeProjectionDeviceEntry(
            device_id="entry_join",
            source_runtime_posture="join_runtime",
            is_runtime_host=True,
        )
        assert e.source_runtime_posture == "join_runtime"
        assert e.is_runtime_host is True

    def test_to_dict_carries_fields(self):
        from contracts.multi_device_runtime_projection import RuntimeProjectionDeviceEntry
        d = RuntimeProjectionDeviceEntry(
            device_id="entry_ser",
            source_runtime_posture="join_runtime",
            is_runtime_host=True,
        ).to_dict()
        assert d["source_runtime_posture"] == "join_runtime"
        assert d["is_runtime_host"] is True

    def test_from_registered_runtime_device_carries_posture(self):
        from contracts.multi_device_runtime_projection import from_registered_runtime_device
        from contracts.registered_runtime_device import from_android_registration
        device = from_android_registration(_android_payload(source_runtime_posture="join_runtime"))
        entry = from_registered_runtime_device(device)
        assert entry.source_runtime_posture == "join_runtime"
        assert entry.is_runtime_host is True

    def test_from_registered_runtime_device_control_only_default(self):
        from contracts.multi_device_runtime_projection import from_registered_runtime_device
        from contracts.registered_runtime_device import RegisteredRuntimeDevice
        device = RegisteredRuntimeDevice(device_id="plain_01")
        entry = from_registered_runtime_device(device)
        assert entry.source_runtime_posture == "control_only"
        assert entry.is_runtime_host is False


# ---------------------------------------------------------------------------
# 7. RuntimeProjectionHostEntry carries source_runtime_posture
# ---------------------------------------------------------------------------

class TestRuntimeProjectionHostEntryPosture:
    """RuntimeProjectionHostEntry carries source_runtime_posture."""

    def test_default_posture_is_control_only(self):
        from contracts.multi_device_runtime_projection import RuntimeProjectionHostEntry
        e = RuntimeProjectionHostEntry(host_id="h_default")
        assert e.source_runtime_posture == "control_only"

    def test_explicit_posture(self):
        from contracts.multi_device_runtime_projection import RuntimeProjectionHostEntry
        e = RuntimeProjectionHostEntry(host_id="h_join", source_runtime_posture="join_runtime")
        assert e.source_runtime_posture == "join_runtime"

    def test_to_dict_carries_posture(self):
        from contracts.multi_device_runtime_projection import RuntimeProjectionHostEntry
        d = RuntimeProjectionHostEntry(
            host_id="h_ser", source_runtime_posture="join_runtime"
        ).to_dict()
        assert d["source_runtime_posture"] == "join_runtime"


# ---------------------------------------------------------------------------
# 8. project_runtime_devices() propagates posture
# ---------------------------------------------------------------------------

class TestProjectRuntimeDevicesPosture:
    """project_runtime_devices() propagates posture fields from device dicts."""

    def test_posture_propagated_from_dict(self):
        from contracts.multi_device_runtime_projection import project_runtime_devices
        devices = [
            {
                "device_id": "ph_proj_1",
                "platform": "android",
                "source_runtime_posture": "join_runtime",
                "is_runtime_host": True,
                "online": True,
            }
        ]
        entries = project_runtime_devices(devices)
        assert len(entries) == 1
        assert entries[0].source_runtime_posture == "join_runtime"
        assert entries[0].is_runtime_host is True

    def test_missing_posture_defaults_to_control_only(self):
        from contracts.multi_device_runtime_projection import project_runtime_devices
        devices = [{"device_id": "ph_proj_2", "platform": "android"}]
        entries = project_runtime_devices(devices)
        assert entries[0].source_runtime_posture == "control_only"
        assert entries[0].is_runtime_host is False

    def test_from_registered_runtime_device_dict_posture_carried(self):
        """project_runtime_devices() picks up posture from RegisteredRuntimeDevice.to_dict()."""
        from contracts.multi_device_runtime_projection import project_runtime_devices
        from contracts.registered_runtime_device import from_android_registration
        device = from_android_registration(_android_payload(source_runtime_posture="join_runtime"))
        entries = project_runtime_devices([device.to_dict()])
        assert entries[0].source_runtime_posture == "join_runtime"
        assert entries[0].is_runtime_host is True


# ---------------------------------------------------------------------------
# 9. project_runtime_hosts() propagates posture
# ---------------------------------------------------------------------------

class TestProjectRuntimeHostsPosture:
    """project_runtime_hosts() propagates source_runtime_posture from host dicts."""

    def test_posture_propagated_from_host_dict(self):
        from contracts.multi_device_runtime_projection import project_runtime_hosts
        hosts = [
            {
                "host_id": "h_proj_1",
                "device_id": "ph_001",
                "source_runtime_posture": "join_runtime",
                "capabilities": {},
            }
        ]
        entries = project_runtime_hosts(hosts)
        assert len(entries) == 1
        assert entries[0].source_runtime_posture == "join_runtime"

    def test_missing_posture_defaults_control_only(self):
        from contracts.multi_device_runtime_projection import project_runtime_hosts
        hosts = [{"host_id": "h_proj_2", "device_id": "ph_002", "capabilities": {}}]
        entries = project_runtime_hosts(hosts)
        assert entries[0].source_runtime_posture == "control_only"

    def test_from_registered_device_to_host_posture_chain(self):
        """full chain: from_android_registration → from_registered_runtime_device (LRH)
        → project_runtime_hosts() preserves posture end-to-end."""
        from contracts.registered_runtime_device import from_android_registration
        from contracts.local_runtime_host import from_registered_runtime_device
        from contracts.multi_device_runtime_projection import project_runtime_hosts

        device = from_android_registration(_android_payload(source_runtime_posture="join_runtime"))
        host = from_registered_runtime_device(device)
        entries = project_runtime_hosts([host.to_dict()])
        assert len(entries) == 1
        assert entries[0].source_runtime_posture == "join_runtime"


# ---------------------------------------------------------------------------
# 10. Policy sentinels
# ---------------------------------------------------------------------------

class TestPolicySentinels:
    """PR-5 policy sentinels are present and non-empty."""

    def test_android_runtime_host_module_sentinels(self):
        from core.android_runtime_host import (
            ANDROID_FIRST_CLASS_RUNTIME_HOST_PR5_SENTINEL,
            ANDROID_RUNTIME_HOST_DISTINCT_FROM_CONNECTED_DEVICE_PR5,
            ANDROID_RUNTIME_HOST_POSTURE_PRESERVED_PR5,
        )
        assert ANDROID_FIRST_CLASS_RUNTIME_HOST_PR5_SENTINEL
        assert ANDROID_RUNTIME_HOST_DISTINCT_FROM_CONNECTED_DEVICE_PR5
        assert ANDROID_RUNTIME_HOST_POSTURE_PRESERVED_PR5

    def test_registered_runtime_device_sentinels(self):
        from contracts.registered_runtime_device import (
            ANDROID_FIRST_CLASS_RUNTIME_HOST_REGISTRATION_PR5,
            ANDROID_REGISTRATION_POSTURE_AWARE_PR5,
        )
        assert ANDROID_FIRST_CLASS_RUNTIME_HOST_REGISTRATION_PR5
        assert ANDROID_REGISTRATION_POSTURE_AWARE_PR5

    def test_local_runtime_host_sentinel(self):
        from contracts.local_runtime_host import LOCAL_RUNTIME_HOST_POSTURE_AWARE_PR5
        assert LOCAL_RUNTIME_HOST_POSTURE_AWARE_PR5


# ---------------------------------------------------------------------------
# 11. Backwards-compatibility: existing fields/defaults unaffected
# ---------------------------------------------------------------------------

class TestBackwardsCompatibility:
    """New PR-5 fields do not break existing contract consumers."""

    def test_registered_runtime_device_existing_fields_unchanged(self):
        from contracts.registered_runtime_device import from_android_registration
        c = from_android_registration(_android_payload())
        # Existing fields still present
        assert c.device_id == "android_ph_001"
        assert c.device_name == "Pixel 9"
        assert c.online is True
        assert c.autonomy.runtime_enabled is True
        assert c.autonomy.supports_remote_handoff is True

    def test_six_information_domains_still_complete(self):
        """All six information domain keys are still present in to_dict()."""
        from contracts.registered_runtime_device import RegisteredRuntimeDevice
        d = RegisteredRuntimeDevice(device_id="compat_01").to_dict()
        required = {
            "device_id", "device_name", "owner_id",
            "platform", "form_factor", "device_type",
            "status", "online", "last_seen",
            "connection", "capabilities", "autonomy",
            "session_presence", "participation_hints", "metadata",
            "source_runtime_posture", "is_runtime_host",
        }
        assert required <= set(d.keys()), f"Missing keys: {required - set(d.keys())}"

    def test_local_runtime_host_existing_fields_unchanged(self):
        from contracts.local_runtime_host import from_registered_runtime_device
        device = _mock_registered_device()
        host = from_registered_runtime_device(device)
        # Existing fields still work
        assert host.device_id == "android_001"
        assert host.host_enabled is True
        assert host.supports_remote_handoff_receive is True

    def test_projection_device_entry_existing_fields_unchanged(self):
        from contracts.multi_device_runtime_projection import RuntimeProjectionDeviceEntry
        e = RuntimeProjectionDeviceEntry(
            device_id="compat_entry",
            platform="android",
            runtime_capable=True,
        )
        assert e.platform == "android"
        assert e.runtime_capable is True
        # New fields have safe defaults
        assert e.source_runtime_posture == "control_only"
        assert e.is_runtime_host is False

    def test_projection_host_entry_existing_fields_unchanged(self):
        from contracts.multi_device_runtime_projection import RuntimeProjectionHostEntry
        e = RuntimeProjectionHostEntry(
            host_id="compat_host",
            device_id="ph_001",
            accepts_handoff=True,
        )
        assert e.accepts_handoff is True
        assert e.source_runtime_posture == "control_only"

    def test_android_role_enum_from_string_unknown_safe(self):
        from core.android_runtime_host import AndroidRuntimeHostRole
        role = AndroidRuntimeHostRole.from_string("totally_unknown_value")
        assert role == AndroidRuntimeHostRole.UNCLASSIFIED

    def test_android_role_enum_from_string_valid_values(self):
        """All canonical string values map to their correct enum members."""
        from core.android_runtime_host import AndroidRuntimeHostRole
        cases = [
            ("full_runtime_host", AndroidRuntimeHostRole.FULL_RUNTIME_HOST),
            ("partial_runtime_host", AndroidRuntimeHostRole.PARTIAL_RUNTIME_HOST),
            ("connected_device_only", AndroidRuntimeHostRole.CONNECTED_DEVICE_ONLY),
            ("unclassified", AndroidRuntimeHostRole.UNCLASSIFIED),
        ]
        for raw, expected in cases:
            assert AndroidRuntimeHostRole.from_string(raw) == expected, (
                f"from_string({raw!r}) should return {expected!r}"
            )


class TestCoreRuntimeModuleExportsPR5:
    """core.runtime re-exports the Android host classification API (PR-5)."""

    def test_android_runtime_host_role_importable_from_core_runtime(self):
        from core.runtime import AndroidRuntimeHostRole
        assert AndroidRuntimeHostRole.FULL_RUNTIME_HOST.value == "full_runtime_host"
        assert AndroidRuntimeHostRole.PARTIAL_RUNTIME_HOST.value == "partial_runtime_host"
        assert AndroidRuntimeHostRole.CONNECTED_DEVICE_ONLY.value == "connected_device_only"
        assert AndroidRuntimeHostRole.UNCLASSIFIED.value == "unclassified"

    def test_android_runtime_host_identity_importable_from_core_runtime(self):
        from core.runtime import AndroidRuntimeHostIdentity
        identity = AndroidRuntimeHostIdentity(device_id="test_001")
        assert identity.device_id == "test_001"
        assert identity.source_runtime_posture == "control_only"

    def test_classify_android_runtime_host_importable_from_core_runtime(self):
        from core.runtime import classify_android_runtime_host, AndroidRuntimeHostRole
        role = classify_android_runtime_host(
            {"source_runtime_posture": "join_runtime", "online": True}
        )
        assert role == AndroidRuntimeHostRole.FULL_RUNTIME_HOST

    def test_build_android_runtime_host_identity_importable_from_core_runtime(self):
        from core.runtime import build_android_runtime_host_identity, AndroidRuntimeHostRole
        identity = build_android_runtime_host_identity(
            {"device_id": "ph_999", "source_runtime_posture": "join_runtime", "online": True}
        )
        assert identity.device_id == "ph_999"
        assert identity.role == AndroidRuntimeHostRole.FULL_RUNTIME_HOST
        assert identity.formation_eligible is True

    def test_pr5_sentinels_importable_from_core_runtime(self):
        from core.runtime import (
            ANDROID_FIRST_CLASS_RUNTIME_HOST_PR5_SENTINEL,
            ANDROID_RUNTIME_HOST_DISTINCT_FROM_CONNECTED_DEVICE_PR5,
            ANDROID_RUNTIME_HOST_POSTURE_PRESERVED_PR5,
        )
        assert ANDROID_FIRST_CLASS_RUNTIME_HOST_PR5_SENTINEL
        assert ANDROID_RUNTIME_HOST_DISTINCT_FROM_CONNECTED_DEVICE_PR5
        assert ANDROID_RUNTIME_HOST_POSTURE_PRESERVED_PR5

    def test_pr5_symbols_in_all_list(self):
        import core.runtime as cr
        for sym in (
            "AndroidRuntimeHostRole",
            "AndroidRuntimeHostIdentity",
            "classify_android_runtime_host",
            "build_android_runtime_host_identity",
            "ANDROID_FIRST_CLASS_RUNTIME_HOST_PR5_SENTINEL",
        ):
            assert sym in cr.__all__, f"{sym!r} missing from core.runtime.__all__"


class TestProjectionRoutesPR5Sentinel:
    """core.routes.projection carries the PR-5 Android runtime host sentinel."""

    def test_android_runtime_host_aligned_pr5_sentinel_present(self):
        from core.routes.projection import ANDROID_RUNTIME_HOST_ALIGNED_PR5
        assert ANDROID_RUNTIME_HOST_ALIGNED_PR5
        assert "PR5" in ANDROID_RUNTIME_HOST_ALIGNED_PR5

    def test_sentinel_indicates_availability(self):
        from core.routes.projection import ANDROID_RUNTIME_HOST_ALIGNED_PR5
        # Must be the "V1" form (available) rather than the fallback UNAVAILABLE form.
        assert "UNAVAILABLE" not in ANDROID_RUNTIME_HOST_ALIGNED_PR5

    def test_pr4_sentinel_still_present(self):
        """Confirm PR-4 sentinel is not disturbed by PR-5 changes."""
        from core.routes.projection import CANONICAL_SESSION_TRUTH_ALIGNED_PR4
        assert CANONICAL_SESSION_TRUTH_ALIGNED_PR4
        assert "UNAVAILABLE" not in CANONICAL_SESSION_TRUTH_ALIGNED_PR4
