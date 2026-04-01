"""
PR-4 Entry-Mode Readiness Resolution — test suite
===================================================

Validates the readiness-based entry-mode resolution logic added to
``resolve_entry_mode`` (``core/unified/entrypoint_router.py``):

1. Explicit ``entry_mode`` override always wins regardless of the rollout flag.
2. Cross-device disabled (``GALAXY_CROSS_DEVICE_ENABLED=0``) → ``"local"``
   regardless of rollout flag.
3. Readiness flag enabled + target device canonically ready → ``"cross_device"``.
4. Readiness flag enabled + target device NOT ready → ``"local"`` (fallback).
5. Readiness flag enabled + two (or more) ready devices + no target → ``"cross_device"``.
6. Readiness flag enabled + fewer than two ready devices + no target → ``"local"``.
7. Readiness flag disabled → legacy behavior (UDM online-count) still works.
"""

from __future__ import annotations

import os
from typing import List
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_udm(count: int) -> MagicMock:
    m = MagicMock()
    m.get_online_count.return_value = count
    return m


def _make_ready_summary(device_id: str) -> MagicMock:
    """Return a mock DeviceReadinessSummary that passes all readiness checks."""
    s = MagicMock()
    s.device_id = device_id
    return s


# ---------------------------------------------------------------------------
# 1. Explicit entry_mode wins regardless of rollout flag
# ---------------------------------------------------------------------------

class TestExplicitEntryModeWins:
    """Explicit caller-supplied entry_mode must bypass all automatic logic."""

    def test_explicit_local_readiness_flag_on(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "1",
            "GALAXY_ENTRYMODE_USE_READINESS": "1",
        }):
            result = resolve_entry_mode(explicit_entry_mode="local")
        assert result == "local"

    def test_explicit_cross_device_readiness_flag_on(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "0",
            "GALAXY_ENTRYMODE_USE_READINESS": "1",
        }):
            result = resolve_entry_mode(explicit_entry_mode="cross_device")
        assert result == "cross_device"

    def test_explicit_hybrid_readiness_flag_on(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "1",
            "GALAXY_ENTRYMODE_USE_READINESS": "1",
        }):
            result = resolve_entry_mode(explicit_entry_mode="hybrid")
        assert result == "hybrid"

    def test_explicit_wins_even_with_ready_devices(self):
        """Explicit local wins even when ready devices would trigger cross_device."""
        from core.unified.entrypoint_router import resolve_entry_mode

        ready = [_make_ready_summary("d1"), _make_ready_summary("d2")]
        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "1",
            "GALAXY_ENTRYMODE_USE_READINESS": "1",
        }):
            with patch(
                "core.device_readiness.get_cross_device_ready_devices",
                return_value=ready,
            ):
                result = resolve_entry_mode(explicit_entry_mode="local")
        assert result == "local"


# ---------------------------------------------------------------------------
# 2. Cross-device disabled → always "local" regardless of readiness flag
# ---------------------------------------------------------------------------

class TestCrossDeviceDisabledAlwaysLocal:
    """When cross-device master switch is off, readiness flag is irrelevant."""

    def test_disabled_readiness_flag_off(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "0",
            "GALAXY_ENTRYMODE_USE_READINESS": "0",
        }):
            result = resolve_entry_mode()
        assert result == "local"

    def test_disabled_readiness_flag_on(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "0",
            "GALAXY_ENTRYMODE_USE_READINESS": "1",
        }):
            result = resolve_entry_mode()
        assert result == "local"

    def test_disabled_with_target_device_readiness_flag_on(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "0",
            "GALAXY_ENTRYMODE_USE_READINESS": "1",
        }):
            with patch(
                "core.device_readiness.is_device_cross_device_ready",
                return_value=True,
            ):
                result = resolve_entry_mode(target_device="dev-001")
        assert result == "local"


# ---------------------------------------------------------------------------
# 3. Readiness flag on + target device ready → "cross_device"
# ---------------------------------------------------------------------------

class TestReadinessFlagTargetDeviceReady:
    """When readiness flag is on and the named target device is ready."""

    def test_target_ready_returns_cross_device(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "1",
            "GALAXY_ENTRYMODE_USE_READINESS": "1",
        }):
            with patch(
                "core.device_readiness.is_device_cross_device_ready",
                return_value=True,
            ):
                result = resolve_entry_mode(target_device="dev-001")
        assert result == "cross_device"

    def test_target_ready_includes_trace_id(self):
        """Resolution should succeed and not raise when trace_id is supplied."""
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "1",
            "GALAXY_ENTRYMODE_USE_READINESS": "1",
        }):
            with patch(
                "core.device_readiness.is_device_cross_device_ready",
                return_value=True,
            ):
                result = resolve_entry_mode(
                    target_device="dev-001",
                    trace_id="trace-abc",
                    source="test",
                )
        assert result == "cross_device"

    def test_calls_is_device_cross_device_ready_with_correct_id(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "1",
            "GALAXY_ENTRYMODE_USE_READINESS": "1",
        }):
            with patch(
                "core.device_readiness.is_device_cross_device_ready",
                return_value=True,
            ) as mock_fn:
                resolve_entry_mode(target_device="my-device")
                mock_fn.assert_called_once_with("my-device")


# ---------------------------------------------------------------------------
# 4. Readiness flag on + target device NOT ready → "local"
# ---------------------------------------------------------------------------

class TestReadinessFlagTargetDeviceNotReady:
    """When readiness flag is on but the target device fails readiness."""

    def test_target_not_ready_returns_local(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "1",
            "GALAXY_ENTRYMODE_USE_READINESS": "1",
        }):
            with patch(
                "core.device_readiness.is_device_cross_device_ready",
                return_value=False,
            ):
                result = resolve_entry_mode(target_device="dev-offline")
        assert result == "local"

    def test_target_readiness_check_raises_returns_local(self):
        """If readiness check raises unexpectedly, fall back gracefully to local."""
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "1",
            "GALAXY_ENTRYMODE_USE_READINESS": "1",
        }):
            with patch(
                "core.device_readiness.is_device_cross_device_ready",
                side_effect=RuntimeError("boom"),
            ):
                result = resolve_entry_mode(target_device="dev-bad")
        assert result == "local"

    def test_target_not_ready_with_trace_id(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "1",
            "GALAXY_ENTRYMODE_USE_READINESS": "1",
        }):
            with patch(
                "core.device_readiness.is_device_cross_device_ready",
                return_value=False,
            ):
                result = resolve_entry_mode(
                    target_device="dev-offline",
                    trace_id="t-999",
                )
        assert result == "local"


# ---------------------------------------------------------------------------
# 5. Readiness flag on + no target + >=2 ready devices → "cross_device"
# ---------------------------------------------------------------------------

class TestReadinessFlagNoTargetTwoReadyDevices:
    """When readiness flag is on, no target, and >=2 ready devices."""

    def test_two_ready_devices_returns_cross_device(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        ready = [_make_ready_summary("d1"), _make_ready_summary("d2")]
        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "1",
            "GALAXY_ENTRYMODE_USE_READINESS": "1",
        }):
            with patch(
                "core.device_readiness.get_cross_device_ready_devices",
                return_value=ready,
            ):
                result = resolve_entry_mode()
        assert result == "cross_device"

    def test_many_ready_devices_returns_cross_device(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        ready = [_make_ready_summary(f"d{i}") for i in range(5)]
        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "1",
            "GALAXY_ENTRYMODE_USE_READINESS": "1",
        }):
            with patch(
                "core.device_readiness.get_cross_device_ready_devices",
                return_value=ready,
            ):
                result = resolve_entry_mode()
        assert result == "cross_device"

    def test_calls_get_cross_device_ready_devices(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        ready = [_make_ready_summary("d1"), _make_ready_summary("d2")]
        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "1",
            "GALAXY_ENTRYMODE_USE_READINESS": "1",
        }):
            with patch(
                "core.device_readiness.get_cross_device_ready_devices",
                return_value=ready,
            ) as mock_fn:
                resolve_entry_mode()
                mock_fn.assert_called_once()


# ---------------------------------------------------------------------------
# 6. Readiness flag on + no target + <2 ready devices → "local"
# ---------------------------------------------------------------------------

class TestReadinessFlagNoTargetFewerThanTwoReady:
    """When readiness flag is on, no target, but fewer than 2 devices ready."""

    def test_one_ready_device_returns_local(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        ready = [_make_ready_summary("d1")]
        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "1",
            "GALAXY_ENTRYMODE_USE_READINESS": "1",
        }):
            with patch(
                "core.device_readiness.get_cross_device_ready_devices",
                return_value=ready,
            ):
                result = resolve_entry_mode()
        assert result == "local"

    def test_zero_ready_devices_returns_local(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "1",
            "GALAXY_ENTRYMODE_USE_READINESS": "1",
        }):
            with patch(
                "core.device_readiness.get_cross_device_ready_devices",
                return_value=[],
            ):
                result = resolve_entry_mode()
        assert result == "local"

    def test_ready_list_raises_returns_local(self):
        """If get_cross_device_ready_devices raises, fall back gracefully."""
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "1",
            "GALAXY_ENTRYMODE_USE_READINESS": "1",
        }):
            with patch(
                "core.device_readiness.get_cross_device_ready_devices",
                side_effect=RuntimeError("udm down"),
            ):
                result = resolve_entry_mode()
        assert result == "local"


# ---------------------------------------------------------------------------
# 7. Readiness flag disabled → legacy behavior still works
# ---------------------------------------------------------------------------

class TestLegacyBehaviorWhenFlagDisabled:
    """When GALAXY_ENTRYMODE_USE_READINESS is off (default), legacy logic applies."""

    def test_two_online_devices_returns_cross_device(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "1",
            "GALAXY_ENTRYMODE_USE_READINESS": "0",
        }):
            with patch(
                "core.unified.device_manager.get_unified_device_manager",
                return_value=_mock_udm(2),
            ):
                result = resolve_entry_mode()
        assert result == "cross_device"

    def test_one_online_device_returns_local(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "1",
            "GALAXY_ENTRYMODE_USE_READINESS": "0",
        }):
            with patch(
                "core.unified.device_manager.get_unified_device_manager",
                return_value=_mock_udm(1),
            ):
                result = resolve_entry_mode()
        assert result == "local"

    def test_target_device_forces_cross_device_legacy(self):
        """Legacy: explicit target_device + cross-device on → cross_device."""
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "1",
            "GALAXY_ENTRYMODE_USE_READINESS": "0",
        }):
            with patch(
                "core.unified.device_manager.get_unified_device_manager",
                return_value=_mock_udm(0),
            ):
                result = resolve_entry_mode(target_device="dev-001")
        assert result == "cross_device"

    def test_readiness_helpers_not_called_when_flag_off(self):
        """Legacy path must not call readiness helpers."""
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "1",
            "GALAXY_ENTRYMODE_USE_READINESS": "0",
        }):
            with patch(
                "core.unified.device_manager.get_unified_device_manager",
                return_value=_mock_udm(2),
            ):
                with patch(
                    "core.device_readiness.get_cross_device_ready_devices",
                ) as mock_ready:
                    resolve_entry_mode()
                    mock_ready.assert_not_called()

    def test_default_flag_absent_uses_legacy(self):
        """When the env var is entirely absent, legacy path is used (default off)."""
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "1"}):
            # Remove the readiness flag if it happens to be set
            os.environ.pop("GALAXY_ENTRYMODE_USE_READINESS", None)
            with patch(
                "core.unified.device_manager.get_unified_device_manager",
                return_value=_mock_udm(3),
            ):
                result = resolve_entry_mode()
        assert result == "cross_device"


# ---------------------------------------------------------------------------
# 8. Observability event payload includes readiness-related fields
# ---------------------------------------------------------------------------

class TestObservabilityEventWithReadiness:
    """Verify that the SEB event payload carries correct fields in readiness path."""

    def test_event_payload_readiness_target_ready(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        captured: list = []

        def fake_emit(event_type, *, source, payload, trace_id=""):
            captured.append(payload)

        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "1",
            "GALAXY_ENTRYMODE_USE_READINESS": "1",
        }):
            with patch(
                "core.device_readiness.is_device_cross_device_ready",
                return_value=True,
            ):
                with patch(
                    "core.state_event_bus.emit",
                    side_effect=fake_emit,
                ):
                    resolve_entry_mode(target_device="d1", trace_id="t1")

        assert len(captured) >= 1
        p = captured[0]
        assert p["entry_mode"] == "cross_device"
        assert p["target_device"] == "d1"
        assert p["trace_id"] == "t1"

    def test_event_payload_readiness_target_not_ready(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        captured: list = []

        def fake_emit(event_type, *, source, payload, trace_id=""):
            captured.append(payload)

        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "1",
            "GALAXY_ENTRYMODE_USE_READINESS": "1",
        }):
            with patch(
                "core.device_readiness.is_device_cross_device_ready",
                return_value=False,
            ):
                with patch(
                    "core.state_event_bus.emit",
                    side_effect=fake_emit,
                ):
                    resolve_entry_mode(target_device="d-offline", trace_id="t2")

        assert len(captured) >= 1
        p = captured[0]
        assert p["entry_mode"] == "local"
        assert p["resolution_source"] == "readiness_target_not_ready"

    def test_event_payload_readiness_two_ready_no_target(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        captured: list = []

        def fake_emit(event_type, *, source, payload, trace_id=""):
            captured.append(payload)

        ready = [_make_ready_summary("d1"), _make_ready_summary("d2")]
        with patch.dict(os.environ, {
            "GALAXY_CROSS_DEVICE_ENABLED": "1",
            "GALAXY_ENTRYMODE_USE_READINESS": "1",
        }):
            with patch(
                "core.device_readiness.get_cross_device_ready_devices",
                return_value=ready,
            ):
                with patch(
                    "core.state_event_bus.emit",
                    side_effect=fake_emit,
                ):
                    resolve_entry_mode(trace_id="t3")

        assert len(captured) >= 1
        p = captured[0]
        assert p["entry_mode"] == "cross_device"
        assert p["device_count"] == 2
