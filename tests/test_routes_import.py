"""
Tests: verify all core/routes modules import and create routers correctly.

Run with:
    pytest tests/test_routes_import.py -v
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helper: build an app with all routes attached
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def full_app():
    """Build FastAPI app with all routes included."""
    app = FastAPI()
    from core.api_routes import create_api_routes
    router = create_api_routes()
    app.include_router(router)
    return app


@pytest.fixture(scope="module")
def client(full_app):
    with TestClient(full_app) as c:
        yield c


# ---------------------------------------------------------------------------
# 1. Module-level import checks
# ---------------------------------------------------------------------------

class TestModuleImports:
    """All route sub-modules must be importable without error."""

    def test_shared_imports(self):
        from core.routes._shared import (
            ConnectionManager, connection_manager,
            registered_devices, task_queue, node_status_cache, command_results,
        )
        assert connection_manager is not None

    def test_models_imports(self):
        from core.routes._models import (
            DeviceRegisterRequest, ChatRequest, CommandStatus,
            UnifiedCommandRequest, TargetResult,
        )
        assert ChatRequest is not None

    def test_helpers_imports(self):
        from core.routes._helpers import nodes_root, _load_node, _execute_node
        import os
        assert os.path.isdir(nodes_root)

    def test_system_module(self):
        from core.routes.system import create_router
        router = create_router()
        assert router is not None

    def test_devices_module(self):
        from core.routes.devices import create_router
        router = create_router()
        assert router is not None

    def test_nodes_module(self):
        from core.routes.nodes import create_router
        router = create_router()
        assert router is not None

    def test_vision_module(self):
        from core.routes.vision import create_router
        router = create_router()
        assert router is not None

    def test_tasks_module(self):
        from core.routes.tasks import create_router
        router = create_router()
        assert router is not None

    def test_command_module(self):
        from core.routes.command import create_router
        router = create_router()
        assert router is not None

    def test_chat_module(self):
        from core.routes.chat import create_router, _is_action_intent
        router = create_router()
        assert router is not None
        assert _is_action_intent("帮我打开微信") is True
        assert _is_action_intent("你好") is False

    def test_ai_module(self):
        from core.routes.ai import create_router
        router = create_router()
        assert router is not None

    def test_monitoring_module(self):
        from core.routes.monitoring import create_router
        router = create_router()
        assert router is not None

    def test_relay_module(self):
        from core.routes.relay import create_router
        router = create_router()
        assert router is not None

    def test_hybrid_module(self):
        from core.routes.hybrid import create_router
        router = create_router()
        assert router is not None

    def test_vault_module(self):
        from core.routes.vault import create_router
        router = create_router()
        assert router is not None

    def test_cost_module(self):
        from core.routes.cost import create_router
        router = create_router()
        assert router is not None

    def test_channels_module(self):
        from core.routes.channels import create_router
        router = create_router()
        assert router is not None

    def test_federation_module(self):
        from core.routes.federation import create_router
        router = create_router()
        assert router is not None


# ---------------------------------------------------------------------------
# 2. Route presence checks (key endpoints must exist in the assembled app)
# ---------------------------------------------------------------------------

class TestRoutePresence:
    """Key routes from all sub-modules must be reachable."""

    def test_system_status(self, client):
        r = client.get("/api/v1/system/status")
        assert r.status_code == 200

    def test_system_health(self, client):
        r = client.get("/api/v1/system/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"

    def test_api_config(self, client):
        r = client.get("/api/config")
        assert r.status_code == 200
        data = r.json()
        assert "api_base_url" in data
        assert "status" in data

    def test_devices_list(self, client):
        r = client.get("/api/v1/devices")
        assert r.status_code == 200
        assert "devices" in r.json()

    def test_nodes_list(self, client):
        r = client.get("/api/v1/nodes")
        assert r.status_code == 200
        assert "nodes" in r.json()

    def test_tasks_list(self, client):
        r = client.get("/api/v1/tasks")
        assert r.status_code == 200

    def test_vault_credentials_list(self, client):
        r = client.get("/api/v1/vault/credentials")
        assert r.status_code == 200

    def test_cost_health(self, client):
        r = client.get("/api/v1/cost/health")
        assert r.status_code in (200, 500)  # 500 if cost_tracker not available

    def test_channels_list(self, client):
        r = client.get("/api/v1/channels")
        assert r.status_code in (200, 500)

    def test_federation_info(self, client):
        r = client.get("/api/v1/federation/info")
        assert r.status_code in (200, 500)

    def test_prometheus_metrics(self, client):
        r = client.get("/metrics")
        assert r.status_code == 200
        assert "process_uptime_seconds" in r.text

    def test_security_stats(self, client):
        r = client.get("/api/v1/security/stats")
        assert r.status_code in (200, 500)


# ---------------------------------------------------------------------------
# 3. Backward-compatibility: models still importable from api_routes
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Pydantic models and singletons must still be importable from api_routes."""

    def test_models_from_api_routes(self):
        from core.api_routes import (
            ChatRequest, DeviceRegisterRequest, CommandStatus,
            connection_manager, registered_devices, task_queue,
        )
        assert ChatRequest is not None
        assert connection_manager is not None

    def test_create_api_routes_callable(self):
        from core.api_routes import create_api_routes
        router = create_api_routes()
        assert router is not None
