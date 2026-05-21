"""
tests/test_pr_system_mode_config.py
=====================================

Tests for the canonical system-mode configuration baseline introduced
by the startup/fabric unification PR.

Covers:
  1. SystemMode enum values.
  2. NetworkMode enum values.
  3. resolve_fabric_config() — default (desktop-local) when no env vars set.
  4. resolve_fabric_config() — desktop-cross-device via GALAXY_SYSTEM_MODE.
  5. resolve_fabric_config() — mode inference from GALAXY_CROSS_DEVICE_ENABLED.
  6. Unknown GALAXY_SYSTEM_MODE falls back to desktop-local.
  7. GALAXY_NATS_ENABLED explicit override (true / false).
  8. GALAXY_NATS_URL explicit set implicitly enables NATS.
  9. GALAXY_FABRIC_STRICT=true makes nats_required=True when nats_enabled=True.
 10. GALAXY_FABRIC_STRICT=true but nats_enabled=False → nats_required=False.
 11. GALAXY_NETWORK_MODE parsing — valid values.
 12. GALAXY_NETWORK_MODE unknown value falls back to local.
 13. GALAXY_TRANSPORT_PRIORITY custom value parsed correctly.
 14. Transport priority defaults: local mode vs cross-device mode.
 15. GALAXY_TAILSCALE_ENABLED parsing.
 16. GALAXY_TAILSCALE_HOST populated correctly.
 17. FabricConfig.is_desktop_local / is_cross_device helpers.
 18. FabricConfig.as_dict() returns all expected keys.
 19. FABRIC_CONFIG singleton is a FabricConfig instance.
 20. SYSTEM_MODE_CONFIG_AUTHORITY sentinel is a non-empty string.
 21. cross_device_enabled derived from mode (no explicit env var).
 22. cross_device_enabled explicit env var overrides derived value.
 23. /health/nats endpoint: required=False in desktop-local + no fabric_strict.
 24. /health/nats endpoint: required=True in desktop-cross-device + fabric_strict.
 25. /health/nats endpoint: system_mode field present in response.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.system_mode import (  # noqa: E402
    FABRIC_CONFIG,
    SYSTEM_MODE_CONFIG_AUTHORITY,
    FabricConfig,
    NetworkMode,
    SystemMode,
    resolve_fabric_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(**kwargs) -> FabricConfig:
    """Build a FabricConfig from a subset of env vars."""
    return resolve_fabric_config(kwargs)


# ===========================================================================
# 1. SystemMode enum values
# ===========================================================================

class TestSystemModeEnum:
    def test_desktop_local_value(self):
        assert SystemMode.DESKTOP_LOCAL.value == "desktop-local"

    def test_desktop_cross_device_value(self):
        assert SystemMode.DESKTOP_CROSS_DEVICE.value == "desktop-cross-device"

    def test_enum_members(self):
        assert set(SystemMode) == {SystemMode.DESKTOP_LOCAL, SystemMode.DESKTOP_CROSS_DEVICE}


# ===========================================================================
# 2. NetworkMode enum values
# ===========================================================================

class TestNetworkModeEnum:
    def test_local(self):
        assert NetworkMode.LOCAL.value == "local"

    def test_lan(self):
        assert NetworkMode.LAN.value == "lan"

    def test_tailscale(self):
        assert NetworkMode.TAILSCALE.value == "tailscale"

    def test_relay(self):
        assert NetworkMode.RELAY.value == "relay"


# ===========================================================================
# 3. Default config (no env vars)
# ===========================================================================

class TestDefaultConfig:
    def test_mode_is_desktop_local(self):
        cfg = _cfg()
        assert cfg.mode == SystemMode.DESKTOP_LOCAL

    def test_nats_enabled_false_by_default(self):
        cfg = _cfg()
        assert cfg.nats_enabled is False

    def test_nats_required_false_by_default(self):
        cfg = _cfg()
        assert cfg.nats_required is False

    def test_fabric_strict_false_by_default(self):
        cfg = _cfg()
        assert cfg.fabric_strict is False

    def test_network_mode_local_by_default(self):
        cfg = _cfg()
        assert cfg.network_mode == NetworkMode.LOCAL

    def test_cross_device_disabled_by_default(self):
        cfg = _cfg()
        assert cfg.cross_device_enabled is False

    def test_tailscale_disabled_by_default(self):
        cfg = _cfg()
        assert cfg.tailscale_enabled is False

    def test_tailscale_host_empty_by_default(self):
        cfg = _cfg()
        assert cfg.tailscale_host == ""

    def test_transport_priority_default_local(self):
        cfg = _cfg()
        assert cfg.transport_priority == ["lan", "internet"]

    def test_nats_url_has_default(self):
        cfg = _cfg()
        assert cfg.nats_url == "nats://localhost:4222"


# ===========================================================================
# 4. desktop-cross-device via GALAXY_SYSTEM_MODE
# ===========================================================================

class TestCrossDeviceMode:
    def test_mode_resolved(self):
        cfg = _cfg(GALAXY_SYSTEM_MODE="desktop-cross-device")
        assert cfg.mode == SystemMode.DESKTOP_CROSS_DEVICE

    def test_nats_enabled_true_in_cross_device(self):
        cfg = _cfg(GALAXY_SYSTEM_MODE="desktop-cross-device")
        assert cfg.nats_enabled is True

    def test_cross_device_enabled_true(self):
        cfg = _cfg(GALAXY_SYSTEM_MODE="desktop-cross-device")
        assert cfg.cross_device_enabled is True

    def test_transport_priority_includes_tailscale(self):
        cfg = _cfg(GALAXY_SYSTEM_MODE="desktop-cross-device")
        assert cfg.transport_priority == ["tailscale", "lan", "internet"]

    def test_nats_required_false_without_strict(self):
        cfg = _cfg(GALAXY_SYSTEM_MODE="desktop-cross-device")
        assert cfg.nats_required is False

    def test_nats_required_true_with_strict(self):
        cfg = _cfg(
            GALAXY_SYSTEM_MODE="desktop-cross-device",
            GALAXY_FABRIC_STRICT="true",
        )
        assert cfg.nats_required is True


# ===========================================================================
# 5. Mode inference from GALAXY_CROSS_DEVICE_ENABLED
# ===========================================================================

class TestModeInference:
    def test_true_implies_cross_device(self):
        cfg = _cfg(GALAXY_CROSS_DEVICE_ENABLED="true")
        assert cfg.mode == SystemMode.DESKTOP_CROSS_DEVICE

    def test_1_implies_cross_device(self):
        cfg = _cfg(GALAXY_CROSS_DEVICE_ENABLED="1")
        assert cfg.mode == SystemMode.DESKTOP_CROSS_DEVICE

    def test_yes_implies_cross_device(self):
        cfg = _cfg(GALAXY_CROSS_DEVICE_ENABLED="yes")
        assert cfg.mode == SystemMode.DESKTOP_CROSS_DEVICE

    def test_false_implies_desktop_local(self):
        cfg = _cfg(GALAXY_CROSS_DEVICE_ENABLED="false")
        assert cfg.mode == SystemMode.DESKTOP_LOCAL

    def test_0_implies_desktop_local(self):
        cfg = _cfg(GALAXY_CROSS_DEVICE_ENABLED="0")
        assert cfg.mode == SystemMode.DESKTOP_LOCAL

    def test_system_mode_wins_over_cross_device_enabled(self):
        # GALAXY_SYSTEM_MODE takes priority
        cfg = _cfg(
            GALAXY_SYSTEM_MODE="desktop-local",
            GALAXY_CROSS_DEVICE_ENABLED="true",
        )
        assert cfg.mode == SystemMode.DESKTOP_LOCAL


# ===========================================================================
# 6. Unknown GALAXY_SYSTEM_MODE falls back to desktop-local
# ===========================================================================

class TestUnknownMode:
    def test_unknown_value_falls_back(self):
        cfg = _cfg(GALAXY_SYSTEM_MODE="unknown-mode")
        assert cfg.mode == SystemMode.DESKTOP_LOCAL


# ===========================================================================
# 7. GALAXY_NATS_ENABLED explicit override
# ===========================================================================

class TestNatsEnabledOverride:
    def test_explicit_true_in_local_mode(self):
        cfg = _cfg(GALAXY_NATS_ENABLED="true")
        assert cfg.nats_enabled is True

    def test_explicit_false_in_cross_device_mode(self):
        cfg = _cfg(
            GALAXY_SYSTEM_MODE="desktop-cross-device",
            GALAXY_NATS_ENABLED="false",
        )
        assert cfg.nats_enabled is False

    def test_explicit_1(self):
        cfg = _cfg(GALAXY_NATS_ENABLED="1")
        assert cfg.nats_enabled is True

    def test_explicit_0(self):
        cfg = _cfg(GALAXY_NATS_ENABLED="0")
        assert cfg.nats_enabled is False


# ===========================================================================
# 8. GALAXY_NATS_URL implicitly enables NATS
# ===========================================================================

class TestNatsUrlImplicit:
    def test_nats_url_enables_nats(self):
        cfg = _cfg(GALAXY_NATS_URL="nats://10.0.0.5:4222")
        assert cfg.nats_enabled is True

    def test_nats_url_overrides_default(self):
        cfg = _cfg(GALAXY_NATS_URL="nats://10.0.0.5:4222")
        assert cfg.nats_url == "nats://10.0.0.5:4222"

    def test_empty_nats_url_uses_default(self):
        cfg = _cfg(GALAXY_NATS_URL="")
        assert cfg.nats_url == "nats://localhost:4222"


# ===========================================================================
# 9–10. GALAXY_FABRIC_STRICT
# ===========================================================================

class TestFabricStrict:
    def test_strict_true_and_nats_enabled_makes_required(self):
        cfg = _cfg(GALAXY_NATS_ENABLED="true", GALAXY_FABRIC_STRICT="true")
        assert cfg.nats_required is True

    def test_strict_true_but_nats_disabled_not_required(self):
        cfg = _cfg(GALAXY_NATS_ENABLED="false", GALAXY_FABRIC_STRICT="true")
        assert cfg.nats_required is False

    def test_strict_false_nats_enabled_not_required(self):
        cfg = _cfg(GALAXY_NATS_ENABLED="true", GALAXY_FABRIC_STRICT="false")
        assert cfg.nats_required is False


# ===========================================================================
# 11–12. GALAXY_NETWORK_MODE
# ===========================================================================

class TestNetworkMode:
    def test_lan(self):
        cfg = _cfg(GALAXY_NETWORK_MODE="lan")
        assert cfg.network_mode == NetworkMode.LAN

    def test_tailscale(self):
        cfg = _cfg(GALAXY_NETWORK_MODE="tailscale")
        assert cfg.network_mode == NetworkMode.TAILSCALE

    def test_relay(self):
        cfg = _cfg(GALAXY_NETWORK_MODE="relay")
        assert cfg.network_mode == NetworkMode.RELAY

    def test_local(self):
        cfg = _cfg(GALAXY_NETWORK_MODE="local")
        assert cfg.network_mode == NetworkMode.LOCAL

    def test_unknown_falls_back_to_local(self):
        cfg = _cfg(GALAXY_NETWORK_MODE="nebula")
        assert cfg.network_mode == NetworkMode.LOCAL


# ===========================================================================
# 13–14. Transport priority
# ===========================================================================

class TestTransportPriority:
    def test_custom_value(self):
        cfg = _cfg(GALAXY_TRANSPORT_PRIORITY="tailscale,intranet,relay")
        assert cfg.transport_priority == ["tailscale", "intranet", "relay"]

    def test_default_local_mode(self):
        cfg = _cfg()
        assert cfg.transport_priority == ["lan", "internet"]

    def test_default_cross_device_mode(self):
        cfg = _cfg(GALAXY_SYSTEM_MODE="desktop-cross-device")
        assert cfg.transport_priority == ["tailscale", "lan", "internet"]

    def test_custom_overrides_mode_default(self):
        cfg = _cfg(
            GALAXY_SYSTEM_MODE="desktop-cross-device",
            GALAXY_TRANSPORT_PRIORITY="relay",
        )
        assert cfg.transport_priority == ["relay"]


# ===========================================================================
# 15–16. Tailscale
# ===========================================================================

class TestTailscale:
    def test_tailscale_enabled_true(self):
        cfg = _cfg(GALAXY_TAILSCALE_ENABLED="true")
        assert cfg.tailscale_enabled is True

    def test_tailscale_enabled_false(self):
        cfg = _cfg(GALAXY_TAILSCALE_ENABLED="false")
        assert cfg.tailscale_enabled is False

    def test_tailscale_host_populated(self):
        cfg = _cfg(GALAXY_TAILSCALE_HOST="my-node.tailscale.net")
        assert cfg.tailscale_host == "my-node.tailscale.net"

    def test_tailscale_host_empty_by_default(self):
        cfg = _cfg()
        assert cfg.tailscale_host == ""


# ===========================================================================
# 17. FabricConfig convenience helpers
# ===========================================================================

class TestFabricConfigHelpers:
    def test_is_desktop_local_true(self):
        cfg = _cfg()
        assert cfg.is_desktop_local is True
        assert cfg.is_cross_device is False

    def test_is_cross_device_true(self):
        cfg = _cfg(GALAXY_SYSTEM_MODE="desktop-cross-device")
        assert cfg.is_cross_device is True
        assert cfg.is_desktop_local is False


# ===========================================================================
# 18. FabricConfig.as_dict()
# ===========================================================================

class TestAsDictMethod:
    def test_all_keys_present(self):
        cfg = _cfg()
        d = cfg.as_dict()
        expected_keys = {
            "mode", "nats_enabled", "nats_url", "nats_required",
            "fabric_strict", "network_mode", "cross_device_enabled",
            "tailscale_enabled", "tailscale_host", "transport_priority",
        }
        assert expected_keys == set(d.keys())

    def test_mode_is_string(self):
        cfg = _cfg()
        assert isinstance(cfg.as_dict()["mode"], str)

    def test_network_mode_is_string(self):
        cfg = _cfg()
        assert isinstance(cfg.as_dict()["network_mode"], str)

    def test_transport_priority_is_list(self):
        cfg = _cfg()
        assert isinstance(cfg.as_dict()["transport_priority"], list)


# ===========================================================================
# 19–20. Module-level exports
# ===========================================================================

class TestModuleExports:
    def test_fabric_config_singleton(self):
        assert isinstance(FABRIC_CONFIG, FabricConfig)

    def test_authority_sentinel_nonempty(self):
        assert isinstance(SYSTEM_MODE_CONFIG_AUTHORITY, str)
        assert len(SYSTEM_MODE_CONFIG_AUTHORITY) > 0

    def test_authority_sentinel_value(self):
        assert SYSTEM_MODE_CONFIG_AUTHORITY == "core.system_mode"


# ===========================================================================
# 21–22. cross_device_enabled derivation
# ===========================================================================

class TestCrossDeviceEnabledDerivation:
    def test_derived_false_in_local_mode(self):
        cfg = _cfg(GALAXY_SYSTEM_MODE="desktop-local")
        assert cfg.cross_device_enabled is False

    def test_derived_true_in_cross_device_mode(self):
        cfg = _cfg(GALAXY_SYSTEM_MODE="desktop-cross-device")
        assert cfg.cross_device_enabled is True

    def test_explicit_override_false_in_cross_device_mode(self):
        cfg = _cfg(
            GALAXY_SYSTEM_MODE="desktop-cross-device",
            GALAXY_CROSS_DEVICE_ENABLED="false",
        )
        assert cfg.cross_device_enabled is False

    def test_explicit_override_true_in_local_mode(self):
        cfg = _cfg(
            GALAXY_SYSTEM_MODE="desktop-local",
            GALAXY_CROSS_DEVICE_ENABLED="true",
        )
        # Note: mode is still desktop-local because GALAXY_SYSTEM_MODE wins,
        # but cross_device_enabled reflects the explicit env var.
        assert cfg.cross_device_enabled is True
        assert cfg.mode == SystemMode.DESKTOP_LOCAL


# ===========================================================================
# 23–25. /health/nats endpoint mode-aware response
# ===========================================================================

class TestNatsHealthEndpoint:
    """Tests for the observability /health/nats endpoint mode fix."""

    def _call_nats_health_with_env(self, env_overrides: dict) -> dict:
        """Patch env vars, build a minimal app, and call GET /health/nats."""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        import os

        original_env = dict(os.environ)
        try:
            # Apply overrides
            for k, v in env_overrides.items():
                os.environ[k] = v
            # Remove keys set to None
            for k, v in env_overrides.items():
                if v is None:
                    os.environ.pop(k, None)

            # Build a minimal app with the observability router
            app = FastAPI()
            from core.routes.observability import create_router
            mock_bus_stats = {"connected": False, "noop_mode": True, "published": 0}
            mock_nats_bus = MagicMock()
            mock_nats_bus.get_stats.return_value = mock_bus_stats

            with patch.dict("sys.modules", {"core.nats_bus": MagicMock(nats_bus=mock_nats_bus)}):
                router = create_router()
                app.include_router(router)
                client = TestClient(app, raise_server_exceptions=True)
                resp = client.get("/health/nats")
                return resp.json()
        finally:
            os.environ.clear()
            os.environ.update(original_env)

    def test_required_false_in_desktop_local(self):
        result = self._call_nats_health_with_env({
            "GALAXY_SYSTEM_MODE": "desktop-local",
            "GALAXY_FABRIC_STRICT": "false",
            "GALAXY_NATS_ENABLED": "false",
        })
        assert result["required"] is False
        assert result["posture"] == "development-allowed-degraded"
        assert result["assertion_ok"] is True

    def test_required_true_in_cross_device_strict(self):
        result = self._call_nats_health_with_env({
            "GALAXY_SYSTEM_MODE": "desktop-cross-device",
            "GALAXY_FABRIC_STRICT": "true",
            "GALAXY_NATS_ENABLED": "true",
        })
        assert result["required"] is True
        assert result["posture"] == "production-required"
        assert result["assertion_ok"] is False

    def test_system_mode_field_present(self):
        result = self._call_nats_health_with_env({
            "GALAXY_SYSTEM_MODE": "desktop-local",
        })
        assert "system_mode" in result

    def test_system_mode_value_desktop_local(self):
        result = self._call_nats_health_with_env({
            "GALAXY_SYSTEM_MODE": "desktop-local",
        })
        assert result["system_mode"] == "desktop-local"


# ===========================================================================
# 26. GET /api/v1/system/mode-status endpoint (Axis-6)
# ===========================================================================

class TestModeStatusEndpoint:
    """Verify GET /api/v1/system/mode-status exposes the canonical mode state.

    Axis-6: Full-end system runtime/surface/capability/protocol closure —
    operators must be able to query the current system mode, cross-device
    capability availability, and takeover readiness via a single endpoint.
    """

    def _call_mode_status_with_env(self, env_overrides: dict) -> dict:
        import os
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from core.routes.system import create_router

        original_env = os.environ.copy()
        try:
            os.environ.clear()
            os.environ.update(env_overrides)

            app = FastAPI()
            router = create_router()
            app.include_router(router)
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.get("/api/v1/system/mode-status")
            assert resp.status_code == 200
            return resp.json()
        finally:
            os.environ.clear()
            os.environ.update(original_env)

    def test_26_01_endpoint_returns_200(self):
        """GET /api/v1/system/mode-status returns HTTP 200."""
        result = self._call_mode_status_with_env({})
        assert isinstance(result, dict)

    def test_26_02_mode_field_present(self):
        """Response includes 'mode' field."""
        result = self._call_mode_status_with_env({})
        assert "mode" in result

    def test_26_03_cross_device_enabled_field_present(self):
        """Response includes 'cross_device_enabled' field."""
        result = self._call_mode_status_with_env({})
        assert "cross_device_enabled" in result

    def test_26_04_takeover_available_field_present(self):
        """Response includes 'takeover_available' field."""
        result = self._call_mode_status_with_env({})
        assert "takeover_available" in result

    def test_26_05_schema_version_present(self):
        """Response includes 'schema_version' field."""
        result = self._call_mode_status_with_env({})
        assert "schema_version" in result
        assert result["schema_version"] == "1.0"

    def test_26_06_desktop_local_mode(self):
        """desktop-local mode is reflected in mode field."""
        result = self._call_mode_status_with_env({"GALAXY_SYSTEM_MODE": "desktop-local"})
        assert result["mode"] == "desktop-local"

    def test_26_07_cross_device_disabled_in_local_mode(self):
        """cross_device_enabled=False in desktop-local mode."""
        result = self._call_mode_status_with_env({
            "GALAXY_SYSTEM_MODE": "desktop-local",
            "GALAXY_CROSS_DEVICE_ENABLED": "0",
        })
        assert result["cross_device_enabled"] is False

    def test_26_08_takeover_not_available_when_cross_device_off(self):
        """takeover_available=False when cross-device is disabled."""
        result = self._call_mode_status_with_env({
            "GALAXY_SYSTEM_MODE": "desktop-local",
            "GALAXY_CROSS_DEVICE_ENABLED": "0",
        })
        assert result["takeover_available"] is False

    def test_26_09_cross_device_mode_reflected(self):
        """desktop-cross-device mode is reflected in mode and cross_device_enabled."""
        result = self._call_mode_status_with_env({
            "GALAXY_SYSTEM_MODE": "desktop-cross-device",
        })
        assert result["mode"] == "desktop-cross-device"
        assert result["cross_device_enabled"] is True

    def test_26_10_takeover_available_in_cross_device_mode(self):
        """takeover_available=True when system is in cross-device mode."""
        result = self._call_mode_status_with_env({
            "GALAXY_SYSTEM_MODE": "desktop-cross-device",
        })
        assert result["takeover_available"] is True

    def test_26_11_android_devices_online_field_present(self):
        """Response includes 'android_devices_online' count field."""
        result = self._call_mode_status_with_env({})
        assert "android_devices_online" in result
        assert isinstance(result["android_devices_online"], int)

    def test_26_12_nats_enabled_field_present(self):
        """Response includes 'nats_enabled' field."""
        result = self._call_mode_status_with_env({})
        assert "nats_enabled" in result
