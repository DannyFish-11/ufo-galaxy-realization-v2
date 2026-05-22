"""PR-8: API compatibility surface boundary containment checks."""

import pytest

from core.api_routes import (
    API_COMPATIBILITY_SURFACE_BOUNDARY_POLICY,
    API_COMPATIBILITY_SURFACE_BOUNDARY_PR8_SENTINEL,
    CANONICAL_API_ROUTES_AUTHORITY,
    PROTECTED_CORE_COMPAT_WS_OVERRIDE_ENV,
    create_websocket_routes,
    get_core_compat_device_ingress_policy,
    get_device_ingress_surface_report,
    get_api_compatibility_surface_registry,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


def test_pr8_compatibility_boundary_sentinels_present() -> None:
    assert CANONICAL_API_ROUTES_AUTHORITY == "core.api_routes"
    assert "API_COMPATIBILITY_SURFACE_BOUNDARY_POLICY_V1" in API_COMPATIBILITY_SURFACE_BOUNDARY_POLICY
    assert "API_COMPATIBILITY_SURFACE_BOUNDARY_PR8_SENTINEL_V1" in API_COMPATIBILITY_SURFACE_BOUNDARY_PR8_SENTINEL


def test_pr8_compatibility_surface_registry_has_expected_surfaces() -> None:
    registry = get_api_compatibility_surface_registry()
    surface_ids = {entry["surface_id"] for entry in registry}
    assert "legacy_android_http_device_routes" in surface_ids
    assert "core_direct_device_websocket_ingress" in surface_ids
    assert all(entry["canonical_replacement"] for entry in registry)


def test_pr8_compatibility_surface_registry_returns_copy() -> None:
    first = get_api_compatibility_surface_registry()
    first.append({"surface_id": "injected"})
    second = get_api_compatibility_surface_registry()
    assert not any(entry.get("surface_id") == "injected" for entry in second)


def test_core_compat_device_ingress_policy_blocks_protected_cross_device_mode() -> None:
    policy = get_core_compat_device_ingress_policy(
        {
            "GALAXY_SYSTEM_MODE": "desktop-cross-device",
            "GALAXY_ENABLE_CORE_COMPAT_WS": "true",
        }
    )
    assert policy["protected_mode"] is True
    assert policy["blocked_by_protected_mode"] is True
    assert policy["effective_enabled"] is False
    assert policy["policy_state"] == "blocked_protected_mode"


def test_core_compat_device_ingress_policy_allows_explicit_local_fallback() -> None:
    policy = get_core_compat_device_ingress_policy(
        {
            "GALAXY_SYSTEM_MODE": "desktop-local",
            "GALAXY_ENABLE_CORE_COMPAT_WS": "true",
        }
    )
    assert policy["protected_mode"] is False
    assert policy["blocked_by_protected_mode"] is False
    assert policy["effective_enabled"] is True
    assert policy["policy_state"] == "enabled"


def test_device_ingress_surface_report_exposes_gateway_registry_and_core_policy() -> None:
    report = get_device_ingress_surface_report(
        {
            "GALAXY_SYSTEM_MODE": "desktop-cross-device",
            "GALAXY_ENABLE_CORE_COMPAT_WS": "true",
        }
    )
    assert report["canonical_device_ingress_authority"]
    canonical = [
        entry
        for entry in report["gateway_device_ingress_surfaces"]
        if entry["classification"] == "canonical"
    ]
    assert len(canonical) == 1
    assert canonical[0]["path"] == "/ws/device/{device_id}"
    assert report["core_compat_device_ingress_policy"]["blocked_by_protected_mode"] is True


def test_core_compat_websocket_rejects_protected_cross_device_mode(monkeypatch) -> None:
    monkeypatch.setenv("GALAXY_SYSTEM_MODE", "desktop-cross-device")
    monkeypatch.setenv("GALAXY_ENABLE_CORE_COMPAT_WS", "true")
    monkeypatch.delenv(PROTECTED_CORE_COMPAT_WS_OVERRIDE_ENV, raising=False)

    app = FastAPI()
    create_websocket_routes(app)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/device/device-compat") as websocket:
            payload = websocket.receive_json()
            assert payload["type"] == "compat_ws_blocked_protected_mode"
            assert payload["policy_state"] == "blocked_protected_mode"
            assert payload["override_env_var"] == PROTECTED_CORE_COMPAT_WS_OVERRIDE_ENV
            with pytest.raises(WebSocketDisconnect) as exc_info:
                websocket.receive_json()
            assert exc_info.value.code == 1008
