"""
tests/test_config_endpoint.py
==============================

Unit tests for ``GET /api/v1/config``.

Covers:
* Status 200 and all required top-level keys are present.
* Default STUN fallback when ``GALAXY_STUN_URLS`` is not set.
* Empty ``turn_servers`` when TURN env vars are absent — must not crash.
* Correct TURN entry shape when TURN is configured.
* ``ws_base`` is derived from ``rest_base`` (http→ws conversion).
* ``transport_priority`` defaults when env not set.
* ``feature_flags`` keys are present and boolean.
* Custom transport priority is respected when env var is set.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

from fastapi import FastAPI
from fastapi.testclient import TestClient

from galaxy_gateway.api.config import build_client_config, router

REQUIRED_KEYS = {
    "ws_base",
    "rest_base",
    "ws_paths",
    "webrtc_gateway_ws_path",
    "stun_servers",
    "turn_servers",
    "transport_priority",
    "feature_flags",
}


def _make_app() -> FastAPI:
    """Minimal FastAPI app that mounts only the config router."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture()
def client(monkeypatch):
    """TestClient with a clean environment for each test."""
    # Remove any GALAXY_* vars that might leak from the host environment
    for var in (
        "GATEWAY_URL",
        "GALAXY_STUN_URLS",
        "GALAXY_TURN_URLS",
        "GALAXY_TURN_USERNAME",
        "GALAXY_TURN_CREDENTIAL",
        "GALAXY_TAILSCALE_ENABLED",
        "GALAXY_TRANSPORT_PRIORITY",
        "GALAXY_USE_GATEWAY_FOR_WEBRTC",
    ):
        monkeypatch.delenv(var, raising=False)

    return TestClient(_make_app())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConfigEndpointStatus:
    def test_returns_200(self, client):
        resp = client.get("/api/v1/config")
        assert resp.status_code == 200

    def test_content_type_json(self, client):
        resp = client.get("/api/v1/config")
        assert "application/json" in resp.headers.get("content-type", "")


class TestRequiredKeys:
    def test_all_required_keys_present(self, client):
        data: Dict[str, Any] = client.get("/api/v1/config").json()
        missing = REQUIRED_KEYS - data.keys()
        assert not missing, f"Missing keys: {missing}"

    def test_ws_paths_is_list(self, client):
        data = client.get("/api/v1/config").json()
        assert isinstance(data["ws_paths"], list)
        assert len(data["ws_paths"]) >= 1

    def test_stun_servers_is_list(self, client):
        data = client.get("/api/v1/config").json()
        assert isinstance(data["stun_servers"], list)

    def test_turn_servers_is_list(self, client):
        data = client.get("/api/v1/config").json()
        assert isinstance(data["turn_servers"], list)

    def test_transport_priority_is_list(self, client):
        data = client.get("/api/v1/config").json()
        assert isinstance(data["transport_priority"], list)

    def test_feature_flags_is_dict(self, client):
        data = client.get("/api/v1/config").json()
        assert isinstance(data["feature_flags"], dict)


class TestDefaultFallbacks:
    def test_stun_fallback_when_env_absent(self, client):
        """When GALAXY_STUN_URLS is not set a default STUN URL is returned."""
        data = client.get("/api/v1/config").json()
        assert len(data["stun_servers"]) >= 1
        assert any("stun:" in s for s in data["stun_servers"])

    def test_turn_empty_when_env_absent(self, client):
        """When GALAXY_TURN_URLS is not set turn_servers must be an empty list."""
        data = client.get("/api/v1/config").json()
        assert data["turn_servers"] == []

    def test_transport_priority_default(self, client):
        data = client.get("/api/v1/config").json()
        assert data["transport_priority"] == ["tailscale", "intranet", "internet"]

    def test_feature_flags_have_expected_keys(self, client):
        data = client.get("/api/v1/config").json()
        flags = data["feature_flags"]
        assert "tailscale_enabled" in flags
        assert "use_gateway_for_webrtc" in flags

    def test_feature_flags_are_bool(self, client):
        data = client.get("/api/v1/config").json()
        for key, val in data["feature_flags"].items():
            assert isinstance(val, bool), f"feature_flags[{key!r}] is not bool"


class TestWsBase:
    def test_ws_base_derived_from_rest_base(self, monkeypatch):
        """ws_base must be the ws:// equivalent of rest_base."""
        monkeypatch.setenv("GATEWAY_URL", "http://192.168.1.5:8765")
        cfg = build_client_config()
        assert cfg["rest_base"] == "http://192.168.1.5:8765"
        assert cfg["ws_base"] == "ws://192.168.1.5:8765"

    def test_wss_base_for_https(self, monkeypatch):
        monkeypatch.setenv("GATEWAY_URL", "https://my.gateway.example.com")
        cfg = build_client_config()
        assert cfg["ws_base"] == "wss://my.gateway.example.com"
        assert cfg["rest_base"] == "https://my.gateway.example.com"


class TestTurnServers:
    def test_turn_entry_present_when_configured(self, monkeypatch):
        monkeypatch.setenv("GALAXY_TURN_URLS", "turn:turn.example.com:3478")
        monkeypatch.setenv("GALAXY_TURN_USERNAME", "testuser")
        monkeypatch.setenv("GALAXY_TURN_CREDENTIAL", "testpass")
        cfg = build_client_config()
        assert len(cfg["turn_servers"]) == 1
        entry = cfg["turn_servers"][0]
        assert "urls" in entry
        assert entry["username"] == "testuser"
        assert entry["credential"] == "testpass"

    def test_turn_entry_no_creds(self, monkeypatch):
        """TURN entry without credentials must still have 'urls' key."""
        monkeypatch.setenv("GALAXY_TURN_URLS", "turn:turn.example.com:3478")
        monkeypatch.delenv("GALAXY_TURN_USERNAME", raising=False)
        monkeypatch.delenv("GALAXY_TURN_CREDENTIAL", raising=False)
        cfg = build_client_config()
        assert len(cfg["turn_servers"]) == 1
        assert "urls" in cfg["turn_servers"][0]

    def test_turn_empty_when_urls_blank(self, monkeypatch):
        monkeypatch.setenv("GALAXY_TURN_URLS", "  ")
        cfg = build_client_config()
        assert cfg["turn_servers"] == []


class TestStunServers:
    def test_custom_stun_from_env(self, monkeypatch):
        monkeypatch.setenv("GALAXY_STUN_URLS", "stun:custom.stun.server:3478")
        cfg = build_client_config()
        assert "stun:custom.stun.server:3478" in cfg["stun_servers"]

    def test_multiple_stun_servers(self, monkeypatch):
        monkeypatch.setenv(
            "GALAXY_STUN_URLS",
            "stun:stun1.example.com:3478,stun:stun2.example.com:3478",
        )
        cfg = build_client_config()
        assert len(cfg["stun_servers"]) == 2


class TestTransportPriority:
    def test_custom_priority_from_env(self, monkeypatch):
        monkeypatch.setenv("GALAXY_TRANSPORT_PRIORITY", "intranet,internet")
        cfg = build_client_config()
        assert cfg["transport_priority"] == ["intranet", "internet"]


class TestFeatureFlags:
    def test_tailscale_enabled_flag(self, monkeypatch):
        monkeypatch.setenv("GALAXY_TAILSCALE_ENABLED", "true")
        cfg = build_client_config()
        assert cfg["feature_flags"]["tailscale_enabled"] is True

    def test_tailscale_disabled_flag(self, monkeypatch):
        monkeypatch.setenv("GALAXY_TAILSCALE_ENABLED", "false")
        cfg = build_client_config()
        assert cfg["feature_flags"]["tailscale_enabled"] is False

    def test_use_gateway_for_webrtc_default_true(self, monkeypatch):
        monkeypatch.delenv("GALAXY_USE_GATEWAY_FOR_WEBRTC", raising=False)
        cfg = build_client_config()
        assert cfg["feature_flags"]["use_gateway_for_webrtc"] is True

    def test_use_gateway_for_webrtc_can_be_disabled(self, monkeypatch):
        monkeypatch.setenv("GALAXY_USE_GATEWAY_FOR_WEBRTC", "false")
        cfg = build_client_config()
        assert cfg["feature_flags"]["use_gateway_for_webrtc"] is False


class TestWsPaths:
    def test_android_path_present(self, client):
        data = client.get("/api/v1/config").json()
        paths = data["ws_paths"]
        assert any("/ws/android" in p for p in paths)

    def test_device_path_present(self, client):
        data = client.get("/api/v1/config").json()
        paths = data["ws_paths"]
        assert any("/ws/device" in p for p in paths)

    def test_webrtc_path_contains_id_placeholder(self, client):
        data = client.get("/api/v1/config").json()
        assert "{id}" in data["webrtc_gateway_ws_path"]
