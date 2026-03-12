"""
tests/test_autonomous_scheduling.py
=====================================

Unit tests for the autonomous-first device scheduling logic introduced in
galaxy_gateway/autonomous_filter.py and its integration points.

Covers:
  1. is_autonomous_device() — metadata flag checks
  2. filter_autonomous_devices() — prefers autonomous, fallback behaviour
  3. prefer_autonomous=False — filter bypassed
  4. Backward compatibility — devices without metadata still route
  5. Device.metadata stored via register_device(metadata=...)
  6. DeviceRouter._select_devices() prefers autonomous device
"""

from __future__ import annotations

import pytest

from galaxy_gateway.autonomous_filter import (
    filter_autonomous_devices,
    is_autonomous_device,
)


# ---------------------------------------------------------------------------
# Helpers / Stubs
# ---------------------------------------------------------------------------

class _FakeDevice:
    """Minimal device stub for filter tests."""

    def __init__(self, device_id: str, status: str = "online", metadata: dict = None):
        self.device_id = device_id
        self.status = status
        self.metadata = metadata or {}


def _make_auto_meta(**overrides) -> dict:
    """Return metadata that qualifies as fully autonomous (all flags True)."""
    base = {
        "goal_execution_enabled": True,
        "parallel_execution_enabled": True,
        "cross_device_enabled": True,
        "device_role": "agent",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. is_autonomous_device
# ---------------------------------------------------------------------------

class TestIsAutonomousDevice:
    def test_full_meta_passes(self):
        assert is_autonomous_device(_make_auto_meta()) is True

    def test_empty_meta_fails(self):
        assert is_autonomous_device({}) is False

    def test_none_meta_fails(self):
        assert is_autonomous_device(None) is False

    def test_missing_goal_fails(self):
        meta = _make_auto_meta()
        del meta["goal_execution_enabled"]
        assert is_autonomous_device(meta) is False

    def test_false_goal_fails(self):
        assert is_autonomous_device(_make_auto_meta(goal_execution_enabled=False)) is False

    def test_missing_parallel_fails(self):
        meta = _make_auto_meta()
        del meta["parallel_execution_enabled"]
        assert is_autonomous_device(meta) is False

    def test_false_parallel_fails(self):
        assert is_autonomous_device(_make_auto_meta(parallel_execution_enabled=False)) is False

    def test_cross_device_not_required_by_default(self):
        meta = _make_auto_meta(cross_device_enabled=False)
        assert is_autonomous_device(meta) is True

    def test_cross_device_required_and_missing_fails(self):
        meta = _make_auto_meta(cross_device_enabled=False)
        assert is_autonomous_device(meta, require_cross_device=True) is False

    def test_cross_device_required_and_present_passes(self):
        assert is_autonomous_device(_make_auto_meta(), require_cross_device=True) is True

    def test_role_match_passes(self):
        assert is_autonomous_device(_make_auto_meta(device_role="worker"), task_role="worker") is True

    def test_role_mismatch_fails(self):
        assert is_autonomous_device(_make_auto_meta(device_role="agent"), task_role="worker") is False

    def test_no_role_in_meta_allows_any_task_role(self):
        meta = _make_auto_meta()
        del meta["device_role"]
        assert is_autonomous_device(meta, task_role="any_role") is True

    def test_task_role_none_skips_role_check(self):
        assert is_autonomous_device(_make_auto_meta(device_role="special"), task_role=None) is True


# ---------------------------------------------------------------------------
# 2. filter_autonomous_devices — prefer autonomous with fallback
# ---------------------------------------------------------------------------

class TestFilterAutonomousDevices:
    """Tests run with prefer_autonomous=True (the default)."""

    def _filter(self, devices, **kwargs):
        return filter_autonomous_devices(
            devices,
            get_metadata=lambda d: d.metadata,
            get_status=lambda d: d.status,
            **kwargs,
        )

    def test_returns_only_autonomous_when_available(self, monkeypatch):
        monkeypatch.setattr(
            "galaxy_gateway.autonomous_filter._prefer_autonomous", lambda: True
        )
        auto = _FakeDevice("auto1", metadata=_make_auto_meta())
        legacy = _FakeDevice("legacy1", metadata={})
        result = self._filter([auto, legacy])
        assert len(result) == 1
        assert result[0].device_id == "auto1"

    def test_fallback_to_online_when_no_autonomous(self, monkeypatch):
        monkeypatch.setattr(
            "galaxy_gateway.autonomous_filter._prefer_autonomous", lambda: True
        )
        legacy1 = _FakeDevice("legacy1", metadata={})
        legacy2 = _FakeDevice("legacy2", metadata={})
        result = self._filter([legacy1, legacy2])
        assert len(result) == 2
        assert {d.device_id for d in result} == {"legacy1", "legacy2"}

    def test_offline_devices_excluded(self, monkeypatch):
        monkeypatch.setattr(
            "galaxy_gateway.autonomous_filter._prefer_autonomous", lambda: True
        )
        offline = _FakeDevice("offline1", status="offline", metadata=_make_auto_meta())
        online_legacy = _FakeDevice("online1", status="online", metadata={})
        result = self._filter([offline, online_legacy])
        # offline autonomous is excluded; online legacy is fallback
        assert len(result) == 1
        assert result[0].device_id == "online1"

    def test_empty_input_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            "galaxy_gateway.autonomous_filter._prefer_autonomous", lambda: True
        )
        assert self._filter([]) == []

    def test_all_offline_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            "galaxy_gateway.autonomous_filter._prefer_autonomous", lambda: True
        )
        d = _FakeDevice("d1", status="offline", metadata=_make_auto_meta())
        assert self._filter([d]) == []

    def test_cross_device_filter_applied(self, monkeypatch):
        monkeypatch.setattr(
            "galaxy_gateway.autonomous_filter._prefer_autonomous", lambda: True
        )
        with_cd = _FakeDevice("cd1", metadata=_make_auto_meta(cross_device_enabled=True))
        without_cd = _FakeDevice("nocd1", metadata=_make_auto_meta(cross_device_enabled=False))
        result = self._filter([with_cd, without_cd], require_cross_device=True)
        assert len(result) == 1
        assert result[0].device_id == "cd1"

    def test_task_role_filter(self, monkeypatch):
        monkeypatch.setattr(
            "galaxy_gateway.autonomous_filter._prefer_autonomous", lambda: True
        )
        worker = _FakeDevice("w1", metadata=_make_auto_meta(device_role="worker"))
        agent = _FakeDevice("a1", metadata=_make_auto_meta(device_role="agent"))
        result = self._filter([worker, agent], task_role="worker")
        assert len(result) == 1
        assert result[0].device_id == "w1"


# ---------------------------------------------------------------------------
# 3. prefer_autonomous=False — filter disabled
# ---------------------------------------------------------------------------

class TestPreferAutonomousFalse:
    def test_returns_all_online_devices(self, monkeypatch):
        monkeypatch.setattr(
            "galaxy_gateway.autonomous_filter._prefer_autonomous", lambda: False
        )
        auto = _FakeDevice("auto1", metadata=_make_auto_meta())
        legacy = _FakeDevice("legacy1", metadata={})
        offline = _FakeDevice("off1", status="offline", metadata=_make_auto_meta())
        result = filter_autonomous_devices(
            [auto, legacy, offline],
            get_metadata=lambda d: d.metadata,
            get_status=lambda d: d.status,
        )
        assert len(result) == 2
        ids = {d.device_id for d in result}
        assert ids == {"auto1", "legacy1"}


# ---------------------------------------------------------------------------
# 4. Backward compatibility — devices without metadata
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    def test_device_without_metadata_field(self, monkeypatch):
        monkeypatch.setattr(
            "galaxy_gateway.autonomous_filter._prefer_autonomous", lambda: True
        )

        class _OldDevice:
            device_id = "old1"
            status = "online"
            # No .metadata attribute at all

        old = _OldDevice()
        result = filter_autonomous_devices(
            [old],
            get_metadata=lambda d: getattr(d, "metadata", {}),
            get_status=lambda d: d.status,
        )
        # Falls back to legacy (online) routing
        assert len(result) == 1
        assert result[0].device_id == "old1"

    def test_none_metadata_treated_as_non_autonomous(self):
        assert is_autonomous_device(None) is False

    def test_empty_metadata_treated_as_non_autonomous(self):
        assert is_autonomous_device({}) is False


# ---------------------------------------------------------------------------
# 5. Device.metadata stored via register_device(metadata=...)
# ---------------------------------------------------------------------------

class TestDeviceMetadataStorage:
    def test_device_stores_metadata(self):
        from galaxy_gateway.device_router import Device

        meta = _make_auto_meta()
        dev = Device("d1", "android", ["screen"], metadata=meta)
        assert dev.metadata == meta

    def test_device_metadata_defaults_to_empty_dict(self):
        from galaxy_gateway.device_router import Device

        dev = Device("d2", "android", ["screen"])
        assert dev.metadata == {}

    def test_device_metadata_none_coerced_to_empty_dict(self):
        from galaxy_gateway.device_router import Device

        dev = Device("d3", "android", ["screen"], metadata=None)
        assert dev.metadata == {}

    def test_register_device_stores_metadata(self):
        from galaxy_gateway.device_router import DeviceRouter

        router = DeviceRouter()
        meta = _make_auto_meta()
        router.register_device("d10", "android", ["screen"], metadata=meta)
        stored = router.get_device("d10")
        assert stored is not None
        assert stored.metadata == meta

    def test_register_device_without_metadata(self):
        from galaxy_gateway.device_router import DeviceRouter

        router = DeviceRouter()
        router.register_device("d11", "android", ["screen"])
        stored = router.get_device("d11")
        assert stored is not None
        assert stored.metadata == {}


# ---------------------------------------------------------------------------
# 6. DeviceRouter._select_devices() prefers autonomous device
# ---------------------------------------------------------------------------

class TestDeviceRouterSelectDevices:
    """Integration-style tests for _select_devices autonomous preference."""

    def _make_router_with_devices(self):
        from galaxy_gateway.device_router import DeviceRouter

        router = DeviceRouter()
        # Register one autonomous android device
        router.register_device(
            "auto_android",
            "android",
            ["screen"],
            metadata=_make_auto_meta(),
        )
        # Register one legacy android device (no autonomous meta)
        router.register_device(
            "legacy_android",
            "android",
            ["screen"],
            metadata={},
        )
        return router

    def test_selects_autonomous_device_when_available(self, monkeypatch):
        monkeypatch.setattr(
            "galaxy_gateway.autonomous_filter._prefer_autonomous", lambda: True
        )
        router = self._make_router_with_devices()
        analysis = {
            "target_device_type": "android",
            "requires_cross_device": False,
            "task_role": None,
        }
        result = router._select_devices(analysis)
        assert len(result) == 1
        assert result[0].device_id == "auto_android"

    def test_falls_back_to_legacy_when_no_autonomous(self, monkeypatch):
        monkeypatch.setattr(
            "galaxy_gateway.autonomous_filter._prefer_autonomous", lambda: True
        )
        from galaxy_gateway.device_router import DeviceRouter

        router = DeviceRouter()
        router.register_device("legacy_only", "android", ["screen"], metadata={})
        analysis = {
            "target_device_type": "android",
            "requires_cross_device": False,
            "task_role": None,
        }
        result = router._select_devices(analysis)
        assert len(result) == 1
        assert result[0].device_id == "legacy_only"

    def test_prefer_autonomous_false_returns_first_online(self, monkeypatch):
        monkeypatch.setattr(
            "galaxy_gateway.autonomous_filter._prefer_autonomous", lambda: False
        )
        router = self._make_router_with_devices()
        analysis = {
            "target_device_type": "android",
            "requires_cross_device": False,
            "task_role": None,
        }
        result = router._select_devices(analysis)
        # Both devices are online; with prefer_autonomous=False any online device is fine
        assert len(result) == 1
