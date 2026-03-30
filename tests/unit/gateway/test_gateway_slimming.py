"""
tests/unit/gateway/test_gateway_slimming.py
===================================
PR-2: Gateway entry slimming and service wiring cleanup.

Verifies:
1. ``galaxy_gateway/app.py`` is materially smaller (≤ 250 lines).
2. New modules exist: middleware, dependencies, bootstrap, routes/*.
3. Key symbols remain importable from ``galaxy_gateway.app`` (backward compat).
4. Route modules export expected symbols.
5. BearerAuthMiddleware still works correctly (smoke test).
6. ChatRequest schema is in galaxy_gateway/routes/chat.py.
7. Module-level globals in app.py are None before startup (not removed).
8. Dependencies module provides expected getter functions.
"""

import importlib
import pathlib
import sys
import types
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ROOT = pathlib.Path(__file__).parent.parent.parent.parent
GW = ROOT / "galaxy_gateway"


def _source(relpath: str) -> str:
    return (ROOT / relpath).read_text(encoding="utf-8")


def _count_lines(relpath: str) -> int:
    return len(_source(relpath).splitlines())


# ============================================================================
# A. Structural: app.py is a thin composition layer
# ============================================================================

class TestAppThin:
    """galaxy_gateway/app.py must be materially smaller after PR-2."""

    def test_app_py_line_count_reduced(self):
        """app.py should be ≤ 250 lines (was 1249 before PR-2)."""
        count = _count_lines("galaxy_gateway/app.py")
        assert count <= 250, (
            f"galaxy_gateway/app.py has {count} lines; expected ≤ 250 after PR-2 slimming."
        )

    def test_app_py_does_not_define_lifespan_inline(self):
        """Lifespan must not be defined inline in app.py (it lives in bootstrap/)."""
        src = _source("galaxy_gateway/app.py")
        # The lifespan function should not be defined in app.py — only imported.
        assert "def lifespan(" not in src, (
            "lifespan() should not be defined in galaxy_gateway/app.py; "
            "it was moved to galaxy_gateway/bootstrap/lifecycle.py"
        )

    def test_app_py_does_not_define_bearerauth_inline(self):
        """BearerAuthMiddleware must not be defined in app.py (it lives in middleware.py)."""
        src = _source("galaxy_gateway/app.py")
        assert "class BearerAuthMiddleware" not in src, (
            "BearerAuthMiddleware should not be defined in galaxy_gateway/app.py; "
            "it was moved to galaxy_gateway/middleware.py"
        )

    def test_app_py_does_not_define_chatrequest_inline(self):
        """ChatRequest must not be defined in app.py (it lives in routes/chat.py)."""
        src = _source("galaxy_gateway/app.py")
        assert "class ChatRequest" not in src, (
            "ChatRequest should not be defined in galaxy_gateway/app.py; "
            "it was moved to galaxy_gateway/routes/chat.py"
        )

    def test_app_py_imports_lifespan_from_bootstrap(self):
        """app.py must import lifespan from the bootstrap package."""
        src = _source("galaxy_gateway/app.py")
        assert "from galaxy_gateway.bootstrap" in src or "from .bootstrap" in src, (
            "galaxy_gateway/app.py must import lifespan from galaxy_gateway.bootstrap"
        )

    def test_app_py_imports_bearerauth_from_middleware(self):
        """app.py must import BearerAuthMiddleware from middleware module."""
        src = _source("galaxy_gateway/app.py")
        assert "from galaxy_gateway.middleware import" in src or "from .middleware import" in src, (
            "galaxy_gateway/app.py must import BearerAuthMiddleware from .middleware"
        )


# ============================================================================
# B. New module files exist
# ============================================================================

class TestNewModulesExist:
    """All newly extracted modules must be present on disk."""

    @pytest.mark.parametrize("relpath", [
        "galaxy_gateway/middleware.py",
        "galaxy_gateway/dependencies.py",
        "galaxy_gateway/bootstrap/__init__.py",
        "galaxy_gateway/bootstrap/lifecycle.py",
        "galaxy_gateway/routes/__init__.py",
        "galaxy_gateway/routes/health.py",
        "galaxy_gateway/routes/devices.py",
        "galaxy_gateway/routes/tasks.py",
        "galaxy_gateway/routes/sessions.py",
        "galaxy_gateway/routes/chat.py",
        "galaxy_gateway/routes/llm.py",
        "galaxy_gateway/routes/websocket.py",
    ])
    def test_module_file_exists(self, relpath: str):
        assert (ROOT / relpath).exists(), f"Expected file not found: {relpath}"


# ============================================================================
# C. Backward-compatibility: key symbols remain importable from app.py
# ============================================================================

class TestBackwardCompatImports:
    """Symbols that were previously exported from galaxy_gateway.app must still
    be importable from there."""

    def test_bearerauthmiddleware_importable_from_app(self):
        from galaxy_gateway.app import BearerAuthMiddleware
        assert BearerAuthMiddleware is not None

    def test_handle_android_ws_importable_from_app(self):
        from galaxy_gateway.app import _handle_android_ws
        assert callable(_handle_android_ws)

    def test_chatrequest_importable_from_app(self):
        from galaxy_gateway.app import ChatRequest
        assert ChatRequest is not None

    def test_app_object_importable(self):
        from galaxy_gateway.app import app
        from fastapi import FastAPI
        assert isinstance(app, FastAPI)

    def test_module_level_globals_exist_in_app(self):
        """Module-level service globals must still exist (initially None)."""
        import galaxy_gateway.app as gw_app
        for name in ("device_manager", "websocket_manager", "task_orchestrator",
                     "message_handler", "openclawd_instance", "llm_router_instance",
                     "nats_adapter", "heartbeat_scheduler"):
            assert hasattr(gw_app, name), (
                f"galaxy_gateway.app must still expose module-level '{name}' for backward compat"
            )


# ============================================================================
# D. Middleware module
# ============================================================================

class TestMiddlewareModule:
    """galaxy_gateway/middleware.py must export BearerAuthMiddleware."""

    def test_bearerauthmiddleware_importable(self):
        from galaxy_gateway.middleware import BearerAuthMiddleware
        assert BearerAuthMiddleware is not None

    def test_auth_exempt_paths_defined(self):
        from galaxy_gateway.middleware import _AUTH_EXEMPT_PATHS
        assert "/health" in _AUTH_EXEMPT_PATHS
        assert "/api/v1/health" in _AUTH_EXEMPT_PATHS

    def test_middleware_smoke(self):
        """BearerAuthMiddleware should pass through requests when auth is disabled."""
        import os
        os.environ.pop("GALAXY_AUTH_ENABLED", None)

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from galaxy_gateway.middleware import BearerAuthMiddleware

        _app = FastAPI()
        _app.add_middleware(BearerAuthMiddleware)

        @_app.get("/health")
        async def h():
            return {"status": "ok"}

        with TestClient(_app, raise_server_exceptions=False) as c:
            resp = c.get("/health")
        assert resp.status_code == 200


# ============================================================================
# E. Dependencies module
# ============================================================================

class TestDependenciesModule:
    """galaxy_gateway/dependencies.py must expose service accessor helpers."""

    @pytest.mark.parametrize("fn_name", [
        "get_device_manager",
        "get_message_handler",
        "get_websocket_manager",
        "get_task_orchestrator",
        "get_nats_adapter",
        "get_openclawd",
        "get_llm_router_instance",
    ])
    def test_helper_callable(self, fn_name: str):
        import galaxy_gateway.dependencies as deps
        fn = getattr(deps, fn_name, None)
        assert callable(fn), f"galaxy_gateway.dependencies.{fn_name} must be callable"

    def test_required_service_raises_503_when_unavailable(self):
        """get_device_manager should raise 503 when app.state.device_manager is None."""
        from fastapi import HTTPException
        from fastapi import FastAPI
        from starlette.testclient import TestClient
        from galaxy_gateway.dependencies import get_device_manager

        _app = FastAPI()

        @_app.get("/test")
        async def _route(dm=__import__("fastapi").Depends(get_device_manager)):
            return {}

        # app.state.device_manager is not set → expect 503
        with TestClient(_app, raise_server_exceptions=False) as c:
            resp = c.get("/test")
        assert resp.status_code == 503


# ============================================================================
# F. Bootstrap module
# ============================================================================

class TestBootstrapModule:
    """galaxy_gateway/bootstrap/ must expose a lifespan context manager."""

    def test_lifespan_importable(self):
        from galaxy_gateway.bootstrap import lifespan
        assert lifespan is not None

    def test_lifespan_is_callable(self):
        from galaxy_gateway.bootstrap import lifespan
        assert callable(lifespan)


# ============================================================================
# G. Route modules
# ============================================================================

class TestRouteModules:
    """Route modules must export their APIRouter instances."""

    @pytest.mark.parametrize("module,attr", [
        ("galaxy_gateway.routes.health", "router"),
        ("galaxy_gateway.routes.devices", "router"),
        ("galaxy_gateway.routes.tasks", "router"),
        ("galaxy_gateway.routes.sessions", "router"),
        ("galaxy_gateway.routes.chat", "router"),
        ("galaxy_gateway.routes.llm", "router"),
    ])
    def test_router_exported(self, module: str, attr: str):
        mod = importlib.import_module(module)
        obj = getattr(mod, attr, None)
        assert obj is not None, f"{module}.{attr} must exist"
        from fastapi import APIRouter
        assert isinstance(obj, APIRouter), f"{module}.{attr} must be an APIRouter"

    def test_websocket_module_exports_register_fn(self):
        from galaxy_gateway.routes.websocket import register_websocket_routes
        assert callable(register_websocket_routes)

    def test_websocket_module_exports_handle_android_ws(self):
        from galaxy_gateway.routes.websocket import _handle_android_ws
        assert callable(_handle_android_ws)


# ============================================================================
# H. ChatRequest schema in routes/chat.py
# ============================================================================

class TestChatRequestInRouteModule:
    """ChatRequest must be defined in galaxy_gateway/routes/chat.py."""

    def test_chatrequest_defined_in_routes_chat(self):
        src = _source("galaxy_gateway/routes/chat.py")
        assert "class ChatRequest" in src, (
            "ChatRequest class must be defined in galaxy_gateway/routes/chat.py"
        )

    def test_multimodal_context_field_in_routes_chat(self):
        src = _source("galaxy_gateway/routes/chat.py")
        assert "multimodal_context" in src, (
            "multimodal_context field must appear in galaxy_gateway/routes/chat.py"
        )

    def test_multimodal_context_forwarded_to_runtime(self):
        src = _source("galaxy_gateway/routes/chat.py")
        assert "multimodal_context=request.multimodal_context" in src, (
            "chat_endpoint must forward multimodal_context to runtime.handle_request()"
        )


# ============================================================================
# I. Lifecycle module
# ============================================================================

class TestLifecycleModule:
    """galaxy_gateway/bootstrap/lifecycle.py must contain expected logic."""

    def test_lifecycle_source_initializes_device_manager(self):
        src = _source("galaxy_gateway/bootstrap/lifecycle.py")
        assert "DeviceManager()" in src, (
            "lifecycle.py must instantiate DeviceManager during startup"
        )

    def test_lifecycle_source_sets_app_state(self):
        src = _source("galaxy_gateway/bootstrap/lifecycle.py")
        assert "app.state" in src, (
            "lifecycle.py must store services on app.state for dependency injection"
        )

    def test_lifecycle_source_updates_module_globals(self):
        src = _source("galaxy_gateway/bootstrap/lifecycle.py")
        assert "_gw_app.websocket_manager" in src or "galaxy_gateway.app" in src, (
            "lifecycle.py must update galaxy_gateway.app module globals for backward compat"
        )
