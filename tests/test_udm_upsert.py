"""
tests/test_udm_upsert.py
========================

PR-2: Tests for upsert_device_state — the unified write API added to
UnifiedDeviceManager as the SSOT single write entry point.

Covers:
  A  upsert_device_state partial status update
  B  upsert_device_state partial capabilities update (full-replace semantics)
  C  upsert_device_state partial metadata update (deep-merge semantics)
  D  state_version increments on every write
  E  updated_at is set on every upsert
  F  upsert returns None for unknown device (no side-effects)
  G  successive upserts accumulate version monotonically
  H  udm_write_upsert SSOT helper delegates to UDM
  I  heartbeat and update_device_status also increment state_version
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_udm():
    from core.unified import device_manager as _mod
    _mod.UnifiedDeviceManager._instance = None


def _fresh_udm():
    _reset_udm()
    from core.unified.device_manager import get_unified_device_manager
    return get_unified_device_manager()


def _register_device(udm, device_id: str, device_type: str = "android"):
    udm.register_device_from_dict(device_id, {"device_type": device_type, "device_name": device_id})


# ===========================================================================
# A  Partial status update
# ===========================================================================

class TestUpsertDeviceStateStatusUpdate:

    def test_status_updated(self):
        udm = _fresh_udm()
        _register_device(udm, "upsert_a_001")

        result = udm.upsert_device_state("upsert_a_001", {"status": "offline"}, source="test")

        assert result is not None
        status_val = result.status.value if hasattr(result.status, "value") else str(result.status)
        assert status_val == "offline"

    def test_status_unchanged_when_not_in_patch(self):
        udm = _fresh_udm()
        _register_device(udm, "upsert_a_002")

        result = udm.upsert_device_state("upsert_a_002", {"device_name": "Renamed"}, source="test")

        assert result is not None
        status_val = result.status.value if hasattr(result.status, "value") else str(result.status)
        # Device was registered → ONLINE; status should not change
        assert status_val == "online"

    def test_status_accepts_enum_instance(self):
        udm = _fresh_udm()
        from core.unified.models import UnifiedDeviceStatus
        _register_device(udm, "upsert_a_003")

        result = udm.upsert_device_state(
            "upsert_a_003",
            {"status": UnifiedDeviceStatus.BUSY},
            source="test",
        )
        assert result is not None
        status_val = result.status.value if hasattr(result.status, "value") else str(result.status)
        assert status_val == "busy"


# ===========================================================================
# B  Capabilities full-replace
# ===========================================================================

class TestUpsertDeviceStateCapabilities:

    def test_capabilities_replaced(self):
        udm = _fresh_udm()
        _register_device(udm, "upsert_b_001")

        # Initial capabilities are empty from register_device_from_dict
        udm.upsert_device_state("upsert_b_001", {"capabilities": ["screen", "touch"]}, source="test")
        dev = udm.get_device("upsert_b_001")
        assert sorted(dev.capabilities) == ["screen", "touch"]

        # Full-replace with new list
        udm.upsert_device_state("upsert_b_001", {"capabilities": ["camera"]}, source="test")
        dev = udm.get_device("upsert_b_001")
        assert dev.capabilities == ["camera"]

    def test_capabilities_not_changed_when_absent(self):
        udm = _fresh_udm()
        udm.register_device_from_dict(
            "upsert_b_002",
            {"device_type": "android", "capabilities": ["screen"]},
        )

        udm.upsert_device_state("upsert_b_002", {"status": "online"}, source="test")
        dev = udm.get_device("upsert_b_002")
        assert "screen" in dev.capabilities


# ===========================================================================
# C  Metadata deep-merge
# ===========================================================================

class TestUpsertDeviceStateMetadata:

    def test_metadata_merged(self):
        udm = _fresh_udm()
        udm.register_device_from_dict(
            "upsert_c_001",
            {"device_type": "android", "extra": {"key_a": "val_a"}},
        )

        udm.upsert_device_state(
            "upsert_c_001",
            {"metadata": {"key_b": "val_b"}},
            source="test",
        )
        dev = udm.get_device("upsert_c_001")
        # key_b must be present in merged metadata
        assert dev.metadata.get("key_b") == "val_b"

    def test_metadata_key_overwritten(self):
        udm = _fresh_udm()
        udm.register_device_from_dict(
            "upsert_c_002",
            {"device_type": "android", "flag": True},
        )

        udm.upsert_device_state(
            "upsert_c_002",
            {"metadata": {"flag": False}},
            source="test",
        )
        dev = udm.get_device("upsert_c_002")
        # Existing key must be overwritten
        assert dev.metadata.get("flag") is False


# ===========================================================================
# D  state_version increments
# ===========================================================================

class TestUpsertStateVersion:

    def test_version_starts_at_zero_after_register(self):
        udm = _fresh_udm()
        _register_device(udm, "upsert_d_001")
        dev = udm.get_device("upsert_d_001")
        assert dev.state_version == 0

    def test_version_increments_on_upsert(self):
        udm = _fresh_udm()
        _register_device(udm, "upsert_d_002")

        udm.upsert_device_state("upsert_d_002", {"status": "online"}, source="test")
        dev = udm.get_device("upsert_d_002")
        assert dev.state_version == 1

        udm.upsert_device_state("upsert_d_002", {"status": "busy"}, source="test")
        dev = udm.get_device("upsert_d_002")
        assert dev.state_version == 2

    def test_version_increments_on_update_device_status(self):
        udm = _fresh_udm()
        from core.unified.models import UnifiedDeviceStatus
        _register_device(udm, "upsert_d_003")

        udm.update_device_status("upsert_d_003", UnifiedDeviceStatus.OFFLINE)
        dev = udm.get_device("upsert_d_003")
        assert dev.state_version == 1

    def test_version_increments_on_heartbeat(self):
        udm = _fresh_udm()
        _register_device(udm, "upsert_d_004")

        udm.heartbeat("upsert_d_004")
        dev = udm.get_device("upsert_d_004")
        assert dev.state_version == 1


# ===========================================================================
# E  updated_at is set on every upsert
# ===========================================================================

class TestUpsertUpdatedAt:

    def test_updated_at_none_after_register(self):
        udm = _fresh_udm()
        _register_device(udm, "upsert_e_001")
        dev = udm.get_device("upsert_e_001")
        assert dev.updated_at is None

    def test_updated_at_set_after_upsert(self):
        udm = _fresh_udm()
        _register_device(udm, "upsert_e_002")

        udm.upsert_device_state("upsert_e_002", {"status": "online"}, source="test")
        dev = udm.get_device("upsert_e_002")
        assert dev.updated_at is not None
        assert isinstance(dev.updated_at, datetime)

    def test_updated_at_advances_on_successive_upserts(self):
        import time
        udm = _fresh_udm()
        _register_device(udm, "upsert_e_003")

        udm.upsert_device_state("upsert_e_003", {"status": "online"}, source="test")
        dev_after_first = udm.get_device("upsert_e_003")
        t1 = dev_after_first.updated_at

        time.sleep(0.01)

        udm.upsert_device_state("upsert_e_003", {"status": "busy"}, source="test")
        dev_after_second = udm.get_device("upsert_e_003")
        t2 = dev_after_second.updated_at

        assert t2 >= t1


# ===========================================================================
# F  upsert returns None for unknown device
# ===========================================================================

class TestUpsertUnknownDevice:

    def test_returns_none_for_unknown(self):
        udm = _fresh_udm()
        result = udm.upsert_device_state("ghost_device_xyz", {"status": "online"}, source="test")
        assert result is None

    def test_no_side_effects_for_unknown(self):
        udm = _fresh_udm()
        udm.upsert_device_state("ghost_device_xyz2", {"status": "online"}, source="test")
        assert udm.get_device("ghost_device_xyz2") is None


# ===========================================================================
# G  Successive upserts accumulate version monotonically
# ===========================================================================

class TestUpsertVersionMonotonic:

    def test_monotonic_version_over_many_upserts(self):
        udm = _fresh_udm()
        _register_device(udm, "upsert_g_001")

        n = 10
        for i in range(n):
            udm.upsert_device_state(
                "upsert_g_001",
                {"status": "online", "metadata": {f"step": i}},
                source="test",
            )

        dev = udm.get_device("upsert_g_001")
        assert dev.state_version == n


# ===========================================================================
# H  udm_write_upsert SSOT helper
# ===========================================================================

class TestSSOTUpsertHelper:

    def test_udm_write_upsert_returns_true_on_success(self):
        _reset_udm()
        from galaxy_gateway.ssot import udm_write_upsert
        from core.unified.device_manager import get_unified_device_manager

        udm = get_unified_device_manager()
        udm.register_device_from_dict("ssot_h_001", {"device_type": "android"})

        result = udm_write_upsert("ssot_h_001", {"status": "online"}, source="test")
        assert result is True

    def test_udm_write_upsert_returns_false_on_failure(self):
        _reset_udm()
        from galaxy_gateway.ssot import udm_write_upsert
        from core.unified.device_manager import get_unified_device_manager
        import core.unified.device_manager as _dm_mod

        # Patch get_unified_device_manager to raise an exception
        with patch.object(_dm_mod, "UnifiedDeviceManager") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.upsert_device_state.side_effect = RuntimeError("UDM error")
            mock_cls.return_value = mock_instance
            _dm_mod.UnifiedDeviceManager._instance = None

            result = udm_write_upsert("ssot_h_002", {"status": "online"}, source="test")
        assert result is False

    def test_udm_write_upsert_updates_state_version(self):
        _reset_udm()
        from galaxy_gateway.ssot import udm_write_upsert
        from core.unified.device_manager import get_unified_device_manager

        udm = get_unified_device_manager()
        udm.register_device_from_dict("ssot_h_003", {"device_type": "android"})

        udm_write_upsert("ssot_h_003", {"status": "busy"}, source="ssot_test")

        dev = udm.get_device("ssot_h_003")
        assert dev.state_version == 1
        status_val = dev.status.value if hasattr(dev.status, "value") else str(dev.status)
        assert status_val == "busy"


# ===========================================================================
# I  heartbeat and update_device_status increment state_version
# ===========================================================================

class TestLegacyWritesBumpVersion:

    def test_heartbeat_bumps_version(self):
        udm = _fresh_udm()
        _register_device(udm, "upsert_i_001")

        udm.heartbeat("upsert_i_001")
        udm.heartbeat("upsert_i_001")

        dev = udm.get_device("upsert_i_001")
        assert dev.state_version == 2

    def test_update_device_status_bumps_version(self):
        udm = _fresh_udm()
        from core.unified.models import UnifiedDeviceStatus
        _register_device(udm, "upsert_i_002")

        udm.update_device_status("upsert_i_002", UnifiedDeviceStatus.OFFLINE)
        udm.update_device_status("upsert_i_002", UnifiedDeviceStatus.ONLINE)

        dev = udm.get_device("upsert_i_002")
        assert dev.state_version == 2

    def test_mixed_writes_version_monotonic(self):
        udm = _fresh_udm()
        from core.unified.models import UnifiedDeviceStatus
        _register_device(udm, "upsert_i_003")

        udm.heartbeat("upsert_i_003")
        udm.update_device_status("upsert_i_003", UnifiedDeviceStatus.BUSY)
        udm.upsert_device_state("upsert_i_003", {"device_name": "Updated"}, source="test")

        dev = udm.get_device("upsert_i_003")
        assert dev.state_version == 3
