"""PR-8: API compatibility surface boundary containment checks."""

from core.api_routes import (
    API_COMPATIBILITY_SURFACE_BOUNDARY_POLICY,
    API_COMPATIBILITY_SURFACE_BOUNDARY_PR8_SENTINEL,
    CANONICAL_API_ROUTES_AUTHORITY,
    get_api_compatibility_surface_registry,
)


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
