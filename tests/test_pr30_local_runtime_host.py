"""tests/test_pr30_local_runtime_host.py
==========================================
Tests for PR-30: Local Runtime Host Contract.

Coverage:
  1. Serialisation stability — to_dict / to_json / from_dict round-trips.
  2. Stable field names — all documented fields present.
  3. Adapter: from_registered_runtime_device normalises RegisteredRuntimeDevice.
  4. Adapter: from_runtime_bridge_config normalises bridge config dict/object.
  5. Builder: build_local_runtime_host produces correct contract.
  6. Summary helper: summarize_local_runtime_host returns compact dict.
  7. Enum helpers — LocalRuntimeHostStatus.from_string / LocalRuntimeExecutionMode.from_string.
  8. Graceful handling of partial / missing data.
  9. Sub-contract field correctness.
  10. contracts package root re-exports.
  11. core.unified package re-exports.
  12. Runtime host API endpoints (read-only, additive).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_rrd(
    *,
    device_id: str = "rrd_dev_001",
    runtime_enabled: bool = True,
    supports_local_autonomy: bool = True,
    supports_remote_handoff: bool = False,
    runtime_id: str = "rt_abc",
    runtime_version: str = "1.2.3",
    active_session_ids: list = None,
    capabilities: list = None,
    online: bool = True,
    status: str = "online",
    preferred_callback_channel: str = "ws",
) -> MagicMock:
    """Return a mock object shaped like RegisteredRuntimeDevice."""
    m = MagicMock()
    m.device_id = device_id
    m.online = online
    m.status = status

    autonomy = MagicMock()
    autonomy.runtime_enabled = runtime_enabled
    autonomy.supports_local_autonomy = supports_local_autonomy
    autonomy.supports_remote_handoff = supports_remote_handoff
    autonomy.runtime_id = runtime_id
    autonomy.runtime_version = runtime_version
    m.autonomy = autonomy

    session_presence = MagicMock()
    session_presence.active_session_ids = list(active_session_ids or [])
    m.session_presence = session_presence

    cap_profile = MagicMock()
    cap_profile.capabilities = list(capabilities or ["screen", "camera"])
    m.capabilities = cap_profile

    hints = MagicMock()
    hints.preferred_callback_channel = preferred_callback_channel
    m.participation_hints = hints

    m.metadata = {}
    return m


def _make_bridge_config_dict(
    *,
    runtime_enabled: bool = True,
    cross_device_enabled: bool = True,
    runtime_url: str = "http://localhost:9000",
    device_id: str = "",
) -> dict:
    return {
        "runtime_enabled": runtime_enabled,
        "cross_device_enabled": cross_device_enabled,
        "runtime_url": runtime_url,
        "device_id": device_id,
    }


# ---------------------------------------------------------------------------
# 1. Serialisation stability
# ---------------------------------------------------------------------------

class TestSerialisationStability:
    """LocalRuntimeHost serialises and round-trips correctly."""

    def test_to_dict_returns_serialisable_dict(self):
        from contracts.local_runtime_host import LocalRuntimeHost
        h = LocalRuntimeHost(device_id="dev_001")
        result = h.to_dict()
        assert isinstance(result, dict)
        assert result["device_id"] == "dev_001"
        # Ensure JSON-serialisable
        json.dumps(result)

    def test_to_json_returns_valid_json(self):
        from contracts.local_runtime_host import LocalRuntimeHost
        h = LocalRuntimeHost(device_id="dev_002", host_enabled=True)
        raw = h.to_json()
        parsed = json.loads(raw)
        assert parsed["device_id"] == "dev_002"
        assert parsed["host_enabled"] is True

    def test_from_dict_round_trip(self):
        from contracts.local_runtime_host import LocalRuntimeHost, LocalRuntimeHostStatus
        original = LocalRuntimeHost(
            device_id="dev_003",
            host_enabled=True,
            host_status=LocalRuntimeHostStatus.ACTIVE,
            supports_local_autonomy=True,
            execution_modes=["local", "hybrid"],
        )
        data = original.to_dict()
        reconstructed = LocalRuntimeHost.from_dict(data)
        assert reconstructed.device_id == original.device_id
        assert reconstructed.host_enabled == original.host_enabled
        assert reconstructed.host_status == original.host_status
        assert reconstructed.supports_local_autonomy == original.supports_local_autonomy

    def test_to_json_then_from_dict_full_round_trip(self):
        from contracts.local_runtime_host import LocalRuntimeHost
        h = LocalRuntimeHost(
            device_id="dev_004",
            runtime_id="rt_123",
            runtime_version="2.0",
            host_enabled=True,
            supports_local_execution=True,
            execution_modes=["local"],
            callback_channels=["ws"],
            capability_summary=["screen"],
        )
        data = json.loads(h.to_json())
        r = LocalRuntimeHost.from_dict(data)
        assert r.runtime_id == "rt_123"
        assert r.execution_modes == ["local"]
        assert r.capability_summary == ["screen"]


# ---------------------------------------------------------------------------
# 2. Stable field names
# ---------------------------------------------------------------------------

class TestStableFieldNames:
    """All documented top-level fields are present in to_dict output."""

    REQUIRED_FIELDS = {
        "host_id",
        "device_id",
        "runtime_id",
        "runtime_version",
        "host_enabled",
        "host_status",
        "supports_local_autonomy",
        "supports_local_execution",
        "supports_local_planning",
        "supports_local_fallback",
        "supports_remote_handoff_receive",
        "supports_remote_handoff_callback",
        "supports_runtime_sessions",
        "active_session_ids",
        "execution_modes",
        "callback_channels",
        "capability_summary",
        "max_concurrent_tasks",
        "current_load",
        "capabilities",
        "sessions",
        "handoff",
        "execution",
        "metadata",
        "recorded_at",
    }

    def test_all_required_fields_present(self):
        from contracts.local_runtime_host import LocalRuntimeHost
        h = LocalRuntimeHost(device_id="dev_fields")
        result = h.to_dict()
        missing = self.REQUIRED_FIELDS - set(result.keys())
        assert not missing, f"Missing fields: {missing}"

    def test_sub_contract_fields_present(self):
        from contracts.local_runtime_host import LocalRuntimeHost
        h = LocalRuntimeHost(device_id="dev_sub")
        result = h.to_dict()
        caps = result["capabilities"]
        assert "supports_local_autonomy" in caps
        assert "supports_local_execution" in caps
        assert "supports_remote_handoff_receive" in caps

        sess = result["sessions"]
        assert "supports_runtime_sessions" in sess
        assert "active_session_ids" in sess

        handoff = result["handoff"]
        assert "supports_remote_handoff_receive" in handoff
        assert "callback_channels" in handoff

        exe = result["execution"]
        assert "supports_local_execution" in exe
        assert "execution_modes" in exe

    def test_host_id_is_auto_generated(self):
        from contracts.local_runtime_host import LocalRuntimeHost
        h1 = LocalRuntimeHost(device_id="dev_a")
        h2 = LocalRuntimeHost(device_id="dev_b")
        assert h1.host_id != h2.host_id
        assert h1.host_id.startswith("lrh_")
        assert h2.host_id.startswith("lrh_")

    def test_host_id_can_be_provided(self):
        from contracts.local_runtime_host import LocalRuntimeHost
        h = LocalRuntimeHost(device_id="dev_c", host_id="custom_host_id")
        assert h.host_id == "custom_host_id"


# ---------------------------------------------------------------------------
# 3. Adapter: from_registered_runtime_device
# ---------------------------------------------------------------------------

class TestFromRegisteredRuntimeDevice:

    def test_basic_fields_mapped(self):
        from contracts.local_runtime_host import from_registered_runtime_device
        rrd = _make_mock_rrd()
        host = from_registered_runtime_device(rrd)
        assert host.device_id == "rrd_dev_001"
        assert host.runtime_id == "rt_abc"
        assert host.runtime_version == "1.2.3"
        assert host.supports_local_autonomy is True
        assert host.supports_local_execution is True  # runtime_enabled=True
        assert host.host_enabled is True  # runtime_enabled and online

    def test_host_status_active_when_enabled_and_online(self):
        from contracts.local_runtime_host import from_registered_runtime_device, LocalRuntimeHostStatus
        rrd = _make_mock_rrd(runtime_enabled=True, online=True)
        host = from_registered_runtime_device(rrd)
        assert host.host_status == LocalRuntimeHostStatus.ACTIVE

    def test_host_status_inactive_when_offline(self):
        from contracts.local_runtime_host import from_registered_runtime_device, LocalRuntimeHostStatus
        rrd = _make_mock_rrd(runtime_enabled=True, online=False)
        host = from_registered_runtime_device(rrd)
        assert host.host_enabled is False
        assert host.host_status == LocalRuntimeHostStatus.INACTIVE

    def test_remote_handoff_receive_mapped(self):
        from contracts.local_runtime_host import from_registered_runtime_device
        rrd = _make_mock_rrd(supports_remote_handoff=True)
        host = from_registered_runtime_device(rrd)
        assert host.supports_remote_handoff_receive is True

    def test_active_session_ids_mapped(self):
        from contracts.local_runtime_host import from_registered_runtime_device
        rrd = _make_mock_rrd(active_session_ids=["s1", "s2"])
        host = from_registered_runtime_device(rrd)
        assert set(host.active_session_ids) == {"s1", "s2"}

    def test_capability_summary_mapped(self):
        from contracts.local_runtime_host import from_registered_runtime_device
        rrd = _make_mock_rrd(capabilities=["screen", "keyboard"])
        host = from_registered_runtime_device(rrd)
        assert "screen" in host.capability_summary
        assert "keyboard" in host.capability_summary

    def test_execution_modes_contain_local(self):
        from contracts.local_runtime_host import from_registered_runtime_device
        rrd = _make_mock_rrd(runtime_enabled=True)
        host = from_registered_runtime_device(rrd)
        assert "local" in host.execution_modes

    def test_callback_channel_from_hints(self):
        from contracts.local_runtime_host import from_registered_runtime_device
        rrd = _make_mock_rrd(supports_remote_handoff=True, preferred_callback_channel="nats")
        host = from_registered_runtime_device(rrd)
        assert "nats" in host.callback_channels

    def test_sub_contracts_populated(self):
        from contracts.local_runtime_host import from_registered_runtime_device
        rrd = _make_mock_rrd(runtime_enabled=True, supports_local_autonomy=True)
        host = from_registered_runtime_device(rrd)
        assert host.capabilities.supports_local_execution is True
        assert host.capabilities.supports_local_autonomy is True
        assert host.sessions.supports_runtime_sessions is True
        assert host.execution.supports_local_execution is True

    def test_from_real_registered_runtime_device(self):
        """Use the actual build_registered_runtime_device builder as source."""
        from contracts.registered_runtime_device import build_registered_runtime_device
        from contracts.local_runtime_host import from_registered_runtime_device
        rrd = build_registered_runtime_device(
            device_id="phone_001",
            device_name="Test Phone",
            platform="android",
            runtime_enabled=True,
            supports_local_autonomy=True,
            supports_remote_handoff=False,
            capabilities=["screen", "camera"],
            status="online",
            online=True,
        )
        host = from_registered_runtime_device(rrd)
        assert host.device_id == "phone_001"
        assert host.supports_local_autonomy is True
        assert host.supports_local_execution is True
        # Serialisation should not raise
        payload = host.to_dict()
        json.dumps(payload)


# ---------------------------------------------------------------------------
# 4. Adapter: from_runtime_bridge_config
# ---------------------------------------------------------------------------

class TestFromRuntimeBridgeConfig:

    def test_dict_config_enabled(self):
        from contracts.local_runtime_host import from_runtime_bridge_config, LocalRuntimeHostStatus
        cfg = _make_bridge_config_dict(runtime_enabled=True, cross_device_enabled=True)
        host = from_runtime_bridge_config(cfg)
        assert host.host_enabled is True
        assert host.host_status == LocalRuntimeHostStatus.ACTIVE
        assert host.supports_local_execution is True
        assert host.supports_remote_handoff_receive is True

    def test_dict_config_disabled_runtime(self):
        from contracts.local_runtime_host import from_runtime_bridge_config, LocalRuntimeHostStatus
        cfg = _make_bridge_config_dict(runtime_enabled=False, cross_device_enabled=False)
        host = from_runtime_bridge_config(cfg)
        assert host.host_enabled is False
        assert host.host_status == LocalRuntimeHostStatus.INACTIVE

    def test_dict_config_cross_device_only(self):
        from contracts.local_runtime_host import from_runtime_bridge_config
        cfg = _make_bridge_config_dict(runtime_enabled=True, cross_device_enabled=True)
        host = from_runtime_bridge_config(cfg)
        assert "remote" in host.execution_modes
        assert "hybrid" in host.execution_modes

    def test_dict_config_no_cross_device(self):
        from contracts.local_runtime_host import from_runtime_bridge_config
        cfg = _make_bridge_config_dict(runtime_enabled=True, cross_device_enabled=False)
        host = from_runtime_bridge_config(cfg)
        assert host.supports_remote_handoff_receive is False
        assert "local" in host.execution_modes

    def test_dict_config_device_id_preserved(self):
        from contracts.local_runtime_host import from_runtime_bridge_config
        cfg = _make_bridge_config_dict(device_id="host_pc_001")
        host = from_runtime_bridge_config(cfg)
        assert host.device_id == "host_pc_001"

    def test_dict_config_auto_device_id_when_empty(self):
        from contracts.local_runtime_host import from_runtime_bridge_config
        cfg = _make_bridge_config_dict(device_id="")
        host = from_runtime_bridge_config(cfg)
        assert host.device_id.startswith("bridge_")

    def test_object_config(self):
        from contracts.local_runtime_host import from_runtime_bridge_config
        cfg = MagicMock()
        cfg.runtime_enabled = True
        cfg.cross_device_enabled = True
        cfg.runtime_url = "http://localhost:9001"
        cfg.device_id = "obj_host_001"
        cfg.runtime_id = None
        cfg.runtime_version = None
        host = from_runtime_bridge_config(cfg)
        assert host.device_id == "obj_host_001"
        assert host.host_enabled is True

    def test_callback_channels_populated_when_url_provided(self):
        from contracts.local_runtime_host import from_runtime_bridge_config
        cfg = _make_bridge_config_dict(runtime_url="http://localhost:9000")
        host = from_runtime_bridge_config(cfg)
        assert "ws" in host.callback_channels

    def test_serialisable_output(self):
        from contracts.local_runtime_host import from_runtime_bridge_config
        cfg = _make_bridge_config_dict()
        host = from_runtime_bridge_config(cfg)
        json.dumps(host.to_dict())


# ---------------------------------------------------------------------------
# 5. Builder: build_local_runtime_host
# ---------------------------------------------------------------------------

class TestBuildLocalRuntimeHost:

    def test_minimal_build(self):
        from contracts.local_runtime_host import build_local_runtime_host
        host = build_local_runtime_host(device_id="dev_min")
        assert host.device_id == "dev_min"
        assert host.host_enabled is False
        assert host.supports_local_autonomy is False

    def test_full_build(self):
        from contracts.local_runtime_host import build_local_runtime_host, LocalRuntimeHostStatus
        host = build_local_runtime_host(
            device_id="dev_full",
            host_id="custom_id",
            runtime_id="rt_xyz",
            runtime_version="3.1.0",
            host_enabled=True,
            host_status="active",
            supports_local_autonomy=True,
            supports_local_execution=True,
            supports_local_planning=True,
            supports_local_fallback=True,
            supports_remote_handoff_receive=True,
            supports_remote_handoff_callback=True,
            supports_runtime_sessions=True,
            max_concurrent_tasks=4,
            current_load=0.5,
            active_session_ids=["s1", "s2"],
            execution_modes=["local", "remote", "hybrid"],
            callback_channels=["ws", "nats"],
            capability_summary=["screen", "camera"],
            metadata={"owner": "user_1"},
        )
        assert host.host_id == "custom_id"
        assert host.device_id == "dev_full"
        assert host.runtime_id == "rt_xyz"
        assert host.runtime_version == "3.1.0"
        assert host.host_enabled is True
        assert host.host_status == LocalRuntimeHostStatus.ACTIVE
        assert host.supports_local_autonomy is True
        assert host.max_concurrent_tasks == 4
        assert host.current_load == 0.5
        assert set(host.active_session_ids) == {"s1", "s2"}
        assert "local" in host.execution_modes
        assert "nats" in host.callback_channels
        assert "screen" in host.capability_summary
        assert host.metadata["owner"] == "user_1"

    def test_sub_contracts_reflect_flags(self):
        from contracts.local_runtime_host import build_local_runtime_host
        host = build_local_runtime_host(
            device_id="dev_sc",
            supports_local_execution=True,
            supports_local_autonomy=True,
            supports_remote_handoff_receive=True,
            callback_channels=["ws"],
        )
        assert host.capabilities.supports_local_execution is True
        assert host.capabilities.supports_local_autonomy is True
        assert host.handoff.supports_remote_handoff_receive is True
        assert "ws" in host.handoff.callback_channels
        assert host.execution.supports_local_execution is True

    def test_serialisable(self):
        from contracts.local_runtime_host import build_local_runtime_host
        host = build_local_runtime_host(device_id="dev_ser", host_enabled=True)
        payload = host.to_dict()
        json.dumps(payload)

    def test_unknown_host_status_defaults_to_inactive(self):
        from contracts.local_runtime_host import build_local_runtime_host, LocalRuntimeHostStatus
        host = build_local_runtime_host(device_id="dev_unk", host_status="totally_unknown")
        assert host.host_status == LocalRuntimeHostStatus.INACTIVE


# ---------------------------------------------------------------------------
# 6. Summary helper: summarize_local_runtime_host
# ---------------------------------------------------------------------------

class TestSummarizeLocalRuntimeHost:

    def test_summary_keys_present(self):
        from contracts.local_runtime_host import build_local_runtime_host, summarize_local_runtime_host
        host = build_local_runtime_host(
            device_id="sum_dev",
            host_enabled=True,
            active_session_ids=["s1"],
        )
        summary = summarize_local_runtime_host(host)
        expected_keys = {
            "host_id", "device_id", "runtime_id", "runtime_version",
            "host_enabled", "host_status",
            "supports_local_autonomy", "supports_local_execution",
            "supports_local_planning", "supports_local_fallback",
            "supports_remote_handoff_receive", "supports_remote_handoff_callback",
            "supports_runtime_sessions",
            "active_session_count", "execution_modes", "callback_channels",
            "capability_summary", "max_concurrent_tasks", "current_load",
            "recorded_at",
        }
        missing = expected_keys - set(summary.keys())
        assert not missing, f"Summary missing keys: {missing}"

    def test_active_session_count(self):
        from contracts.local_runtime_host import build_local_runtime_host, summarize_local_runtime_host
        host = build_local_runtime_host(device_id="sum2", active_session_ids=["a", "b", "c"])
        summary = summarize_local_runtime_host(host)
        assert summary["active_session_count"] == 3

    def test_summary_is_json_serialisable(self):
        from contracts.local_runtime_host import build_local_runtime_host, summarize_local_runtime_host
        host = build_local_runtime_host(device_id="sum3")
        json.dumps(summarize_local_runtime_host(host))

    def test_summary_does_not_include_sub_contracts(self):
        from contracts.local_runtime_host import build_local_runtime_host, summarize_local_runtime_host
        host = build_local_runtime_host(device_id="sum4")
        summary = summarize_local_runtime_host(host)
        # Sub-contracts should not appear in the summary
        assert "capabilities" not in summary
        assert "sessions" not in summary
        assert "handoff" not in summary
        assert "execution" not in summary


# ---------------------------------------------------------------------------
# 7. Enum helpers
# ---------------------------------------------------------------------------

class TestEnumHelpers:

    def test_host_status_from_string_known(self):
        from contracts.local_runtime_host import LocalRuntimeHostStatus
        assert LocalRuntimeHostStatus.from_string("active") == LocalRuntimeHostStatus.ACTIVE
        assert LocalRuntimeHostStatus.from_string("inactive") == LocalRuntimeHostStatus.INACTIVE
        assert LocalRuntimeHostStatus.from_string("degraded") == LocalRuntimeHostStatus.DEGRADED
        assert LocalRuntimeHostStatus.from_string("error") == LocalRuntimeHostStatus.ERROR
        assert LocalRuntimeHostStatus.from_string("starting") == LocalRuntimeHostStatus.STARTING
        assert LocalRuntimeHostStatus.from_string("stopping") == LocalRuntimeHostStatus.STOPPING

    def test_host_status_from_string_unknown_defaults_to_inactive(self):
        from contracts.local_runtime_host import LocalRuntimeHostStatus
        result = LocalRuntimeHostStatus.from_string("not_a_real_status")
        assert result == LocalRuntimeHostStatus.INACTIVE

    def test_host_status_from_string_uppercase(self):
        from contracts.local_runtime_host import LocalRuntimeHostStatus
        assert LocalRuntimeHostStatus.from_string("ACTIVE") == LocalRuntimeHostStatus.ACTIVE

    def test_execution_mode_from_string_known(self):
        from contracts.local_runtime_host import LocalRuntimeExecutionMode
        assert LocalRuntimeExecutionMode.from_string("local") == LocalRuntimeExecutionMode.LOCAL
        assert LocalRuntimeExecutionMode.from_string("remote") == LocalRuntimeExecutionMode.REMOTE
        assert LocalRuntimeExecutionMode.from_string("hybrid") == LocalRuntimeExecutionMode.HYBRID
        assert LocalRuntimeExecutionMode.from_string("fallback") == LocalRuntimeExecutionMode.FALLBACK

    def test_execution_mode_from_string_unknown_defaults_to_local(self):
        from contracts.local_runtime_host import LocalRuntimeExecutionMode
        result = LocalRuntimeExecutionMode.from_string("unknown_mode")
        assert result == LocalRuntimeExecutionMode.LOCAL


# ---------------------------------------------------------------------------
# 8. Graceful handling of partial / missing data
# ---------------------------------------------------------------------------

class TestGracefulPartialData:

    def test_from_registered_runtime_device_none_fields(self):
        """from_registered_runtime_device handles an object with all None fields."""
        from contracts.local_runtime_host import from_registered_runtime_device
        m = MagicMock()
        m.device_id = None
        m.online = None
        m.status = None
        m.autonomy = None
        m.session_presence = None
        m.capabilities = None
        m.participation_hints = None
        m.metadata = None
        host = from_registered_runtime_device(m)
        # Should not raise; device_id may be auto-generated
        assert isinstance(host.device_id, str)
        assert isinstance(host.to_dict(), dict)

    def test_from_registered_runtime_device_exception_returns_minimal(self):
        """When adapter source raises unexpectedly, a minimal contract is returned."""
        from contracts.local_runtime_host import from_registered_runtime_device

        class Broken:
            @property
            def device_id(self):
                raise RuntimeError("boom")

        host = from_registered_runtime_device(Broken())
        assert isinstance(host, __import__("contracts.local_runtime_host",
                                            fromlist=["LocalRuntimeHost"]).LocalRuntimeHost)

    def test_from_runtime_bridge_config_empty_dict(self):
        from contracts.local_runtime_host import from_runtime_bridge_config
        host = from_runtime_bridge_config({})
        assert isinstance(host.device_id, str)
        assert isinstance(host.to_dict(), dict)

    def test_from_runtime_bridge_config_broken_object(self):
        from contracts.local_runtime_host import from_runtime_bridge_config

        class Broken:
            @property
            def runtime_enabled(self):
                raise ValueError("oops")

        host = from_runtime_bridge_config(Broken())
        assert isinstance(host.device_id, str)

    def test_build_local_runtime_host_empty_lists_default(self):
        from contracts.local_runtime_host import build_local_runtime_host
        host = build_local_runtime_host(device_id="dev_empty")
        assert host.active_session_ids == []
        assert host.execution_modes == []
        assert host.callback_channels == []
        assert host.capability_summary == []

    def test_metadata_tolerance(self):
        from contracts.local_runtime_host import build_local_runtime_host
        host = build_local_runtime_host(
            device_id="dev_meta",
            metadata={"nested": {"a": 1}, "list": [1, 2, 3]},
        )
        assert host.metadata["nested"]["a"] == 1
        json.dumps(host.to_dict())


# ---------------------------------------------------------------------------
# 9. Sub-contract field correctness
# ---------------------------------------------------------------------------

class TestSubContractFieldCorrectness:

    def test_capabilities_sub_contract(self):
        from contracts.local_runtime_host import LocalRuntimeHostCapabilities
        caps = LocalRuntimeHostCapabilities(
            supports_local_autonomy=True,
            supports_local_execution=True,
            supports_local_planning=False,
            supports_local_fallback=True,
            supports_remote_handoff_receive=True,
            supports_remote_handoff_callback=True,
            supports_runtime_sessions=True,
        )
        assert caps.supports_local_autonomy is True
        assert caps.supports_local_planning is False
        assert caps.supports_remote_handoff_receive is True

    def test_session_support_sub_contract(self):
        from contracts.local_runtime_host import LocalRuntimeSessionSupport
        sess = LocalRuntimeSessionSupport(
            supports_runtime_sessions=True,
            max_concurrent_tasks=8,
            current_load=0.25,
            active_session_ids=["x", "y"],
        )
        assert sess.max_concurrent_tasks == 8
        assert sess.current_load == 0.25
        assert "x" in sess.active_session_ids

    def test_handoff_support_sub_contract(self):
        from contracts.local_runtime_host import LocalRuntimeHandoffSupport
        h = LocalRuntimeHandoffSupport(
            supports_remote_handoff_receive=True,
            supports_remote_handoff_callback=True,
            callback_channels=["ws", "webrtc"],
        )
        assert h.supports_remote_handoff_receive is True
        assert "webrtc" in h.callback_channels

    def test_execution_support_sub_contract(self):
        from contracts.local_runtime_host import LocalRuntimeExecutionSupport
        e = LocalRuntimeExecutionSupport(
            supports_local_execution=True,
            supports_local_planning=True,
            supports_local_autonomy=True,
            supports_local_fallback=False,
            execution_modes=["local", "hybrid"],
        )
        assert e.supports_local_execution is True
        assert e.supports_local_fallback is False
        assert "hybrid" in e.execution_modes


# ---------------------------------------------------------------------------
# 10. contracts package root re-exports
# ---------------------------------------------------------------------------

class TestContractsPackageExports:

    def test_local_runtime_host_importable(self):
        from contracts import LocalRuntimeHost
        assert LocalRuntimeHost is not None

    def test_status_enum_importable(self):
        from contracts import LocalRuntimeHostStatus
        assert LocalRuntimeHostStatus.ACTIVE.value == "active"

    def test_all_sub_contract_types_importable(self):
        from contracts import (
            LocalRuntimeHostCapabilities,
            LocalRuntimeSessionSupport,
            LocalRuntimeHandoffSupport,
            LocalRuntimeExecutionSupport,
            LocalRuntimeExecutionMode,
        )
        for cls in (
            LocalRuntimeHostCapabilities,
            LocalRuntimeSessionSupport,
            LocalRuntimeHandoffSupport,
            LocalRuntimeExecutionSupport,
            LocalRuntimeExecutionMode,
        ):
            assert cls is not None

    def test_all_adapter_functions_importable(self):
        from contracts import (
            from_registered_runtime_device,
            from_runtime_bridge_config,
            build_local_runtime_host,
            summarize_local_runtime_host,
        )
        for fn in (
            from_registered_runtime_device,
            from_runtime_bridge_config,
            build_local_runtime_host,
            summarize_local_runtime_host,
        ):
            assert callable(fn)

    def test_pr29_exports_still_work(self):
        """PR-30 must not break the PR-29 RegisteredRuntimeDevice exports."""
        from contracts import RegisteredRuntimeDevice, build_registered_runtime_device
        assert RegisteredRuntimeDevice is not None
        assert callable(build_registered_runtime_device)

    def test_pr25_exports_still_work(self):
        """PR-30 must not break the PR-25 ExecutionTrace exports."""
        from contracts import ExecutionTraceEnvelope, ExecutionTraceStage
        assert ExecutionTraceEnvelope is not None
        assert ExecutionTraceStage.INTENT_CREATED is not None


# ---------------------------------------------------------------------------
# 11. core.unified package re-exports
# ---------------------------------------------------------------------------

class TestCoreUnifiedReexports:

    def test_local_runtime_host_in_core_unified(self):
        from core.unified import LocalRuntimeHost
        assert LocalRuntimeHost is not None

    def test_builder_in_core_unified(self):
        from core.unified import build_local_runtime_host
        assert callable(build_local_runtime_host)

    def test_adapters_in_core_unified(self):
        from core.unified import (
            from_registered_runtime_device,
            from_runtime_bridge_config,
            summarize_local_runtime_host,
        )
        assert callable(from_registered_runtime_device)
        assert callable(from_runtime_bridge_config)
        assert callable(summarize_local_runtime_host)

    def test_status_enum_in_core_unified(self):
        from core.unified import LocalRuntimeHostStatus
        assert LocalRuntimeHostStatus.ACTIVE.value == "active"

    def test_pr29_still_exported_from_core_unified(self):
        from core.unified import RegisteredRuntimeDevice, build_registered_runtime_device
        assert RegisteredRuntimeDevice is not None
        assert callable(build_registered_runtime_device)


# ---------------------------------------------------------------------------
# 12. Runtime host API endpoints
# ---------------------------------------------------------------------------

class TestRuntimeHostEndpoints:
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

    def test_list_runtime_hosts_returns_200(self, app_client):
        resp = app_client.get("/api/v1/devices/runtime-hosts")
        assert resp.status_code == 200
        data = resp.json()
        assert "runtime_hosts" in data
        assert "count" in data
        assert isinstance(data["runtime_hosts"], list)
        assert isinstance(data["count"], int)

    def test_list_runtime_hosts_is_read_only_get(self, app_client):
        resp = app_client.post("/api/v1/devices/runtime-hosts")
        assert resp.status_code == 405

    def test_get_runtime_host_unknown_device_returns_404(self, app_client):
        resp = app_client.get("/api/v1/devices/nonexistent_device_pr30_xyz/runtime-host")
        assert resp.status_code == 404

    def test_get_runtime_host_is_read_only_get(self, app_client):
        resp = app_client.post("/api/v1/devices/nonexistent/runtime-host")
        assert resp.status_code == 405

    def test_registered_device_returns_runtime_host_contract(self, app_client):
        """Register a device then retrieve its runtime host contract."""
        reg_payload = {
            "device_id": "pr30_test_dev_001",
            "device_name": "PR30 Test Device",
            "device_type": "windows",
            "capabilities": ["screen", "keyboard"],
        }
        reg_resp = app_client.post("/api/v1/devices/register", json=reg_payload)
        if reg_resp.status_code == 200:
            host_resp = app_client.get("/api/v1/devices/pr30_test_dev_001/runtime-host")
            assert host_resp.status_code == 200
            data = host_resp.json()
            assert data["device_id"] == "pr30_test_dev_001"
            # All required fields must be present
            required = {
                "host_id", "device_id", "host_enabled", "host_status",
                "supports_local_autonomy", "supports_local_execution",
                "supports_remote_handoff_receive", "capabilities",
                "sessions", "handoff", "execution", "metadata",
            }
            missing = required - set(data.keys())
            assert not missing, f"Missing keys in runtime-host response: {missing}"

    def test_runtime_hosts_list_json_serialisable(self, app_client):
        resp = app_client.get("/api/v1/devices/runtime-hosts")
        assert resp.status_code == 200
        # Should be valid JSON (TestClient already parses it)
        data = resp.json()
        json.dumps(data)  # must not raise
