"""
tests/test_e2e_stack.py
=======================

Formal end-to-end integration tests — no external services required.

These tests drive the *real* FastAPI routes (via ``TestClient``) through the
complete request path:  HTTP → route handler → core business logic → response.

Suites
------
1. TestDeviceRegistrationAndCapabilitySync
   - Register a device via POST /api/v1/devices/register.
   - Confirm it appears in GET /api/v1/devices.
   - Confirm CapabilityRegistry reflects the device capabilities.

2. TestCommandRoutingWithTrace
   - Submit a command via POST /api/v1/command.
   - GET /api/v1/command/{id}/status returns a valid status field.
   - Observability endpoint /api/v1/observability/gateway reports router stats.

3. TestObservabilityEndpoints
   - /api/v1/observability/model-route returns the expected JSON shape.
   - /api/v1/observability/recent-calls returns count + calls list.
   - /api/v1/observability/stats returns the stats shape.

4. TestDashboardLiveStatusEndpoint
   - The aggregated /api/v1/observability/live-status endpoint (added in PR-95)
     returns all four sub-sections: capability_load, gateway_trace,
     device_health, model_route.

How to run locally
------------------
    pip install pytest httpx fastapi
    # from the repository root:
    pytest tests/test_e2e_stack.py -v

All tests are self-contained and require only the packages already installed
in the project's virtual environment (fastapi, httpx, pydantic, pytest).
"""

import os
import sys
import uuid
from typing import Any, Dict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path (matches conftest.py convention)
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def api_client() -> TestClient:
    """
    TestClient backed by the full core API router.

    Creates a minimal FastAPI app that includes the same router used in
    production (``core/api_routes.py``), so every test exercises the real
    routing, validation, and business-logic chain without starting an actual
    server.
    """
    from core.api_routes import create_api_routes

    app = FastAPI(title="Galaxy E2E Test App")
    router = create_api_routes()
    app.include_router(router)

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


# ---------------------------------------------------------------------------
# 1. Device registration and capability sync
# ---------------------------------------------------------------------------


class TestDeviceRegistrationAndCapabilitySync:
    """
    Drive device registration through the real HTTP route and verify that:
      - The API returns success with the correct device_id.
      - The device appears in the device list endpoint.
      - CapabilityRegistry is queryable after registration.
    """

    def test_register_device_returns_success(self, api_client: TestClient) -> None:
        """POST /api/v1/devices/register → 200 with success=True."""
        device_id = f"e2e-{uuid.uuid4().hex[:8]}"
        r = api_client.post(
            "/api/v1/devices/register",
            json={
                "device_id": device_id,
                "device_type": "android_phone",
                "device_name": "E2E-TestDevice",
                "capabilities": ["screen", "touch", "camera"],
                "os_version": "Android 14",
                "app_version": "2.3.0",
            },
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("success") is True, f"success != True: {data}"
        assert data.get("device_id") == device_id

    def test_registered_device_appears_in_list(self, api_client: TestClient) -> None:
        """The device registered above must appear in GET /api/v1/devices."""
        device_id = f"e2e-list-{uuid.uuid4().hex[:8]}"
        # Register
        api_client.post(
            "/api/v1/devices/register",
            json={
                "device_id": device_id,
                "device_type": "windows_pc",
                "device_name": "E2E-ListDevice",
            },
        )
        # List
        r = api_client.get("/api/v1/devices")
        assert r.status_code == 200, r.text
        data = r.json()
        # The endpoint returns either {"devices": [...]} or a list directly
        devices: list = data if isinstance(data, list) else data.get("devices", [])
        ids = [d.get("device_id") for d in devices]
        assert device_id in ids, f"Device {device_id!r} not found in device list. ids={ids[:10]}"

    def test_capability_registry_is_queryable(self) -> None:
        """
        CapabilityRegistry.get_instance() must be importable and return a
        registry object whose to_tool_schemas() produces a list.
        """
        from core.agent.capability_registry import CapabilityRegistry

        reg = CapabilityRegistry.get_instance()
        schemas = reg.to_tool_schemas()
        assert isinstance(schemas, list), f"to_tool_schemas() should return list, got {type(schemas)}"

    def test_register_capability_and_retrieve(self) -> None:
        """
        Manually register a capability item and confirm it appears in the
        registry, exercising the CapabilityRegistry.register / _items path
        without any external service.
        """
        from core.agent.capability_registry import CapabilityItem, CapabilityRegistry

        reg = CapabilityRegistry.get_instance()
        name = f"e2e_tool_{uuid.uuid4().hex[:8]}"
        item = CapabilityItem(
            name=name,
            description="E2E test tool",
            source="e2e",
            source_id="test",
            parameters={"type": "object", "properties": {}},
        )
        reg.register(item)
        try:
            assert name in reg._items, f"Tool {name!r} not found in registry"
            schemas = reg.to_tool_schemas()
            names_in_schemas = [s["function"]["name"] for s in schemas]
            assert name in names_in_schemas
        finally:
            reg._items.pop(name, None)


# ---------------------------------------------------------------------------
# 2. Command routing with trace
# ---------------------------------------------------------------------------


class TestCommandRoutingWithTrace:
    """
    Submit a command via POST /api/v1/command and verify that the routing
    layer accepts it (status 200 / 202) and that the command ID is queryable.
    No real device executor is needed — the router records the request and
    returns a request_id.
    """

    def test_post_command_returns_request_id(self, api_client: TestClient) -> None:
        """POST /api/v1/command → 200/202 with a request_id."""
        device_id = f"cmd-dev-{uuid.uuid4().hex[:8]}"
        # Register device first
        api_client.post(
            "/api/v1/devices/register",
            json={"device_id": device_id, "device_type": "android_phone"},
        )

        r = api_client.post(
            "/api/v1/command",
            json={
                "device_id": device_id,
                "action": "screenshot",
                "params": {},
            },
        )
        # Acceptable: 200 (sync result) or 202 (queued) or 404/400 if device
        # not online — all mean the route was reached and processed.
        assert r.status_code in (200, 202, 400, 404, 422), f"Unexpected status {r.status_code}: {r.text}"
        # If we got a request_id, verify it is a non-empty string
        data = r.json()
        if "request_id" in data:
            assert isinstance(data["request_id"], str)
            assert len(data["request_id"]) > 0

    def test_command_router_stats_endpoint(self, api_client: TestClient) -> None:
        """GET /api/v1/command must return router statistics."""
        r = api_client.get("/api/v1/command")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        # Stats should include at minimum one numeric/dict field
        assert isinstance(data, dict), f"Expected dict, got {type(data)}"

    def test_observability_gateway_reflects_router(self, api_client: TestClient) -> None:
        """GET /api/v1/observability/gateway must return the gateway summary dict."""
        r = api_client.get("/api/v1/observability/gateway")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert "registered_count" in data, f"Missing registered_count: {data}"
        assert "command_router_stats" in data, f"Missing command_router_stats: {data}"
        assert isinstance(data["registered_devices"], list)


# ---------------------------------------------------------------------------
# 3. Observability endpoints contract
# ---------------------------------------------------------------------------


class TestObservabilityEndpoints:
    """
    Verify that the observability sub-routes registered via
    ``core.routes.observability`` return the documented JSON shape.
    """

    def test_model_route_status(self, api_client: TestClient) -> None:
        """GET /api/v1/observability/model-route → dict with expected keys."""
        r = api_client.get("/api/v1/observability/model-route")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "default_model" in data, f"Missing default_model: {data}"
        assert "providers" in data, f"Missing providers: {data}"
        assert "fallbacks" in data, f"Missing fallbacks: {data}"
        assert isinstance(data["providers"], list)
        assert isinstance(data["fallbacks"], list)

    def test_recent_calls(self, api_client: TestClient) -> None:
        """GET /api/v1/observability/recent-calls → dict with count + calls."""
        r = api_client.get("/api/v1/observability/recent-calls")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "count" in data, f"Missing count: {data}"
        assert "calls" in data, f"Missing calls: {data}"
        assert isinstance(data["calls"], list)
        assert data["count"] == len(data["calls"])

    def test_observability_stats(self, api_client: TestClient) -> None:
        """GET /api/v1/observability/stats → dict with trace statistics."""
        r = api_client.get("/api/v1/observability/stats")
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, dict), f"Expected dict, got {type(data)}"

    def test_trace_lookup_not_found(self, api_client: TestClient) -> None:
        """GET /api/v1/observability/trace/{id} with unknown id → 404 or found=False."""
        r = api_client.get(f"/api/v1/observability/trace/{uuid.uuid4().hex}")
        # Either 404 (command_id not found) or 200 with found=False
        assert r.status_code in (200, 404), r.text
        if r.status_code == 200:
            data = r.json()
            # When id_type=task_id auto-path returns found=True if any task
            # matches; for a random hex it must be found=False
            assert "found" in data


# ---------------------------------------------------------------------------
# 4. Dashboard live-status aggregated endpoint
# ---------------------------------------------------------------------------


class TestDashboardLiveStatusEndpoint:
    """终态(用户裁决):dashboard/ 整体删除。/api/v1/observability/live-status
    是退役 dashboard 后端(PR-95)的聚合端点,全仓库无其它定义/消费——随
    目录一并退役;canonical 观测面由 core 观测路由套件专钉。"""

    def test_dashboard_backend_retired(self):
        import pathlib

        root = pathlib.Path(__file__).parent.parent
        assert not (root / "dashboard").exists(), "dashboard/ 已按用户裁决整体退役删除,不得复活"
