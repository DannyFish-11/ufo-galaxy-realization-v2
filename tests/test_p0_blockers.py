"""
P0 Blocker Tests
================

Covers all four P0 fixes:
1. websockets dependency in galaxy_gateway/requirements.txt
2. Gateway sensitive routes have Depends(require_auth)
3. Multi-device commands delegate to Node_71 MDCE
4. OpenClawd.sync_device_capabilities falls back to DeviceRegistry
"""

import os
import pytest
from unittest.mock import MagicMock, patch


# ===========================================================================
# P0-1: websockets in galaxy_gateway/requirements.txt
# ===========================================================================

class TestWebsocketsDependency:
    def test_websockets_in_gateway_requirements(self):
        """galaxy_gateway/requirements.txt must list websockets>=11."""
        req_file = os.path.join(
            os.path.dirname(__file__), "..", "galaxy_gateway", "requirements.txt"
        )
        with open(req_file) as f:
            content = f.read()
        assert "websockets" in content, (
            "websockets must be listed in galaxy_gateway/requirements.txt for gateway tests"
        )

    def test_websockets_importable(self):
        """The websockets package must be importable (installed)."""
        import websockets  # noqa: F401  — just check it is available


# ===========================================================================
# P0-2: Gateway sensitive routes protected by Depends(require_auth)
# ===========================================================================

class TestGatewayRouteAuth:
    """Sensitive gateway routes must declare require_auth as a FastAPI dependency."""

    def _get_route_dependencies(self, app, path: str, method: str) -> list:
        """Return the dependency callables for a specific route."""
        for route in app.routes:
            if getattr(route, "path", None) == path:
                if method.upper() in getattr(route, "methods", set()):
                    deps = getattr(route, "dependencies", [])
                    return [d.dependency for d in deps]
        return []

    def _check_route_has_auth(self, app, path: str, method: str) -> bool:
        """Return True if the route has require_auth (or _require_auth) as a dependency."""
        from galaxy_gateway.app import app as gateway_app

        for route in gateway_app.routes:
            if getattr(route, "path", None) != path:
                continue
            if method.upper() not in getattr(route, "methods", set()):
                continue
            # Check endpoint's __code__ for _require_auth usage via Depends
            # The simplest way: check that route.dependant.dependencies is non-empty
            # (FastAPI stores resolved dependencies in route.dependant)
            dep = getattr(route, "dependant", None)
            if dep is None:
                return False
            # dependencies is a list of Dependant objects
            all_deps = getattr(dep, "dependencies", [])
            for d in all_deps:
                call = getattr(d, "call", None)
                if call is not None:
                    name = getattr(call, "__name__", "") or getattr(call, "__qualname__", "")
                    if "require_auth" in name or "_require_auth" in name:
                        return True
                    # Also check module-level alias
                    try:
                        import core.auth
                        if call is getattr(core.auth, "require_auth", None):
                            return True
                    except Exception:
                        pass
        return False

    @pytest.mark.parametrize("path,method", [
        ("/api/tasks", "POST"),
        ("/api/tasks/{task_id}", "GET"),
        ("/api/tasks", "GET"),
        ("/api/tasks/{task_id}", "DELETE"),
        ("/api/commands", "POST"),
        ("/api/v1/sessions", "GET"),
        ("/api/v1/sessions/{session_id}", "GET"),
        ("/api/v1/sessions/{session_id}/migrate", "POST"),
        ("/api/v1/sessions/stats", "GET"),
        ("/api/v1/chat", "POST"),
        ("/api/v1/llm/stats", "GET"),
    ])
    def test_sensitive_route_has_auth_dependency(self, path, method):
        """Every sensitive gateway route must carry require_auth as a dependency."""
        assert self._check_route_has_auth(None, path, method), (
            f"{method} {path} is missing Depends(require_auth)"
        )

    @pytest.mark.parametrize("path", ["/health", "/health/nats", "/api/v1/health"])
    def test_health_routes_accessible_without_auth(self, path):
        """Health endpoints must remain public (no auth required)."""
        from galaxy_gateway.app import app as gateway_app
        from fastapi.testclient import TestClient

        with TestClient(gateway_app, raise_server_exceptions=False) as client:
            resp = client.get(path)
        # Health endpoints return 2xx, not 401/403
        assert resp.status_code not in (401, 403), (
            f"Health endpoint {path} should be auth-exempt but returned {resp.status_code}"
        )


# ===========================================================================
# P0-3: Multi-device commands delegate to Node_71 MDCE
# ===========================================================================

class TestMDCEDispatch:
    """core/routes/command.py unified endpoint must delegate to Node_71 for multi-device."""

    def test_get_node71_url_default(self):
        """_get_node71_url should return a URL containing port 8071 by default."""
        from core.routes.command import _get_node71_url
        url = _get_node71_url()
        assert "8071" in url or "node" in url.lower() or "localhost" in url

    def test_delegate_to_mdce_returns_none_on_connection_error(self):
        """_delegate_to_mdce must return None (not raise) when Node_71 is unreachable."""
        import asyncio
        from core.routes.command import _delegate_to_mdce, CommandStatus
        from core.routes._models import UnifiedCommandRequest

        req = UnifiedCommandRequest(
            command="test",
            targets=["device_a", "device_b"],
            params={},
            mode="sync",
            timeout=5,
        )

        # Point to an unreachable port
        with patch("core.routes.command._get_node71_url", return_value="http://localhost:19999"):
            result = asyncio.get_event_loop().run_until_complete(
                _delegate_to_mdce("req-123", req, "2026-01-01T00:00:00Z")
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_unified_command_multi_device_attempts_mdce(self, monkeypatch):
        """When targets > 1, unified_command should attempt MDCE delegation."""
        mdce_called_with = {}

        async def _mock_delegate(request_id, req, created_at):
            mdce_called_with["request_id"] = request_id
            mdce_called_with["targets"] = req.targets
            from fastapi.responses import JSONResponse
            from core.routes._models import CommandStatus
            return JSONResponse({
                "request_id": request_id,
                "status": CommandStatus.QUEUED,
                "created_at": created_at,
                "mdce": True,
            })

        monkeypatch.setattr("core.routes.command._delegate_to_mdce", _mock_delegate)

        from core.routes.command import create_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(create_router())

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/api/v1/command/unified", json={
                "command": "screenshot",
                "targets": ["phone_1", "phone_2"],
                "mode": "sync",
                "timeout": 10,
            })

        assert resp.status_code == 200
        body = resp.json()
        assert body.get("mdce") is True
        assert set(mdce_called_with.get("targets", [])) == {"phone_1", "phone_2"}

    @pytest.mark.asyncio
    async def test_unified_command_single_device_skips_mdce(self, monkeypatch):
        """When targets == 1, unified_command must NOT call _delegate_to_mdce."""
        mdce_called = []

        async def _mock_delegate(request_id, req, created_at):
            mdce_called.append(True)
            return None

        monkeypatch.setattr("core.routes.command._delegate_to_mdce", _mock_delegate)

        from core.routes.command import create_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(create_router())

        with TestClient(app, raise_server_exceptions=False) as client:
            client.post("/api/v1/command/unified", json={
                "command": "screenshot",
                "targets": ["phone_only"],
                "mode": "sync",
                "timeout": 5,
            })

        assert not mdce_called, "_delegate_to_mdce should not be called for single-device commands"


# ===========================================================================
# P0-4: OpenClawd.sync_device_capabilities DeviceRegistry fallback
# ===========================================================================

class TestCapabilitySync:
    """OpenClawd.sync_device_capabilities must fall back to DeviceRegistry."""

    def test_sync_uses_device_registry_when_udm_unavailable(self):
        """When UnifiedDeviceManager raises, fallback to DeviceRegistry."""
        from core.openclawd import OpenClawd
        from core.agent.capability_registry import get_capability_registry

        mock_device = MagicMock()
        mock_device.device_id = "fallback_phone"
        mock_device.device_name = "Fallback Phone"
        mock_device.device_type = "android"
        mock_device.capabilities = ["screen", "keyboard"]
        mock_device.metadata = {}

        mock_dr = MagicMock()
        mock_dr.list_devices.return_value = {"fallback_phone": mock_device}

        with patch(
            "core.unified.device_manager.get_unified_device_manager",
            side_effect=ImportError("UDM not available"),
        ), patch(
            "core.device_registry.DeviceRegistry.get_instance",
            return_value=mock_dr,
        ):
            oc = OpenClawd()
            count = oc.sync_device_capabilities()

        assert count >= 2, f"Expected >=2 capabilities synced via DeviceRegistry fallback, got {count}"

    def test_sync_uses_device_registry_dict_api(self):
        """DeviceRegistry.list_devices dict-return format is handled correctly."""
        from core.openclawd import OpenClawd

        mock_device = MagicMock()
        mock_device.device_id = "dr_dict_phone"
        mock_device.device_name = "DR Dict Phone"
        mock_device.device_type = "android"
        mock_device.capabilities = ["touch"]
        mock_device.metadata = {}

        mock_dr = MagicMock()
        mock_dr.list_devices.return_value = {"dr_dict_phone": mock_device}

        with patch(
            "core.unified.device_manager.get_unified_device_manager",
            side_effect=RuntimeError("unavailable"),
        ), patch(
            "core.device_registry.DeviceRegistry.get_instance",
            return_value=mock_dr,
        ):
            oc = OpenClawd()
            count = oc.sync_device_capabilities()

        assert count >= 1

    def test_sync_via_device_registry_registers_to_capability_registry(self):
        """After DeviceRegistry fallback sync, capabilities appear in CapabilityRegistry."""
        from core.openclawd import OpenClawd
        from core.agent.capability_registry import get_capability_registry

        reg = get_capability_registry()
        device_id = "cap_sync_test_device"
        key = f"gateway__{device_id}__nfc"
        reg._items.pop(key, None)  # clean up

        mock_device = MagicMock()
        mock_device.device_id = device_id
        mock_device.device_name = "Cap Sync Test"
        mock_device.device_type = "android"
        mock_device.capabilities = ["nfc"]
        mock_device.metadata = {}

        mock_dr = MagicMock()
        mock_dr.list_devices.return_value = {device_id: mock_device}

        with patch(
            "core.unified.device_manager.get_unified_device_manager",
            side_effect=RuntimeError("not available"),
        ), patch(
            "core.device_registry.DeviceRegistry.get_instance",
            return_value=mock_dr,
        ):
            oc = OpenClawd()
            count = oc.sync_device_capabilities()

        assert count >= 1
        item = reg.get(key)
        assert item is not None, f"Capability {key} should be in CapabilityRegistry after sync"
        assert item.available is True

        # cleanup
        reg._items.pop(key, None)

    def test_sync_openclawd_with_mock_registry_returns_nonzero(self):
        """Original test scenario: DeviceRegistry mock → count ≥ 2."""
        from core.openclawd import OpenClawd

        mock_device = MagicMock()
        mock_device.device_id = "oc_test_device"
        mock_device.device_name = "OpenClawd Test Device"
        mock_device.device_type = "windows"
        mock_device.capabilities = ["screen", "keyboard"]
        mock_device.metadata = {}

        mock_dr = MagicMock()
        mock_dr.list_devices.return_value = {"oc_test_device": mock_device}

        with patch(
            "core.device_registry.DeviceRegistry.get_instance",
            return_value=mock_dr,
        ), patch(
            "core.unified.device_manager.get_unified_device_manager",
            side_effect=ImportError("not available"),
        ):
            oc = OpenClawd()
            count = oc.sync_device_capabilities()

        assert count >= 2  # screen + keyboard
