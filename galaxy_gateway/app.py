"""
galaxy_gateway/app.py — Internal Cross-Device Execution Substrate (WebSocket Adapter)
=======================================================================================

**Unified-Subject Architecture — Internal Gateway (NOT a primary entrypoint)**
-------------------------------------------------------------------------------
``galaxy_gateway`` is the *internal cross-device execution substrate* of the
unified subject.  It is the transport/protocol layer that enables the subject's
liminal cross-device execution loop to reach remote devices.

This module is a **WebSocket protocol adapter** — it is NOT a primary subject
entrypoint and does NOT have subject-core authority.  The subject's authority
flows through :class:`~core.desktop_presence_runtime.DesktopPresenceRuntime`
→ :class:`~core.openclawd.OpenClawd` → :mod:`~core.command_router`.

In the unified subject architecture::

    Subject (DesktopPresenceRuntime + OpenClawd)
        └─ cross-device liminal branch → CommandRouter
              └─ CommandRouter calls galaxy_gateway (internal substrate)
                    └─ galaxy_gateway → WebSocket → remote devices

The gateway does NOT initiate subject lifecycle; it receives routed commands
from the subject core and forwards them to device endpoints.

**This module's responsibilities (WebSocket protocol adapter)**

1. WebSocket endpoints: device connection, Android bridge, WebRTC signaling.
2. Device lifecycle management (register / heartbeat / disconnect) via WebSocket.
3. Session roaming REST endpoints (gateway-specific session roaming logic).
4. Health check endpoints (gateway self-status).

**REST API authority** lives in ``core/api_routes.py``.  REST endpoints in
this file are convenience interfaces for standalone gateway deployments only.
In unified deployment mode, ``unified_launcher.py`` mounts ``core/api_routes.py``
as the canonical API surface.

Add new general API endpoints in ``core/routes/`` — not here.
New routes belong in ``galaxy_gateway/routes/``.
Lifecycle/bootstrap logic lives in ``galaxy_gateway/bootstrap/lifecycle.py``.
Service dependency helpers live in ``galaxy_gateway/dependencies.py``.
The Bearer-auth middleware lives in ``galaxy_gateway/middleware.py``.

Middleware stack (executes in LIFO order — first registered runs last)
----------------------------------------------------------------------
1. SecurityHeadersMiddleware — adds security headers to all responses
2. RequestIdMiddleware — assigns UUID request IDs for tracing
3. BearerAuthMiddleware — optional bearer token authentication
4. CORSMiddleware — CORS handling for cross-origin requests
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nodes.common.cors_config import get_cors_origins, get_cors_methods, get_cors_headers
# ── New sub-modules (extracted from this file) ──
from galaxy_gateway.bootstrap.lifecycle import lifespan
from galaxy_gateway.middleware import (
    BearerAuthMiddleware,
    SecurityHeadersMiddleware,
    RequestIdMiddleware,
)
from galaxy_gateway.routes import (
    health_router,
    devices_router,
    tasks_router,
    sessions_router,
    chat_router,
    llm_router,
    register_websocket_routes,
    _handle_android_ws,  # re-exported: tests import from here
)
from galaxy_gateway.routes.chat import ChatRequest  # re-exported: tests inspect this module

# Re-export ChatRequest symbols for backward-compatible source checks
# (multimodal_context field lives in galaxy_gateway.routes.chat but tests
# also check this module's source for: multimodal_context=request.multimodal_context)
# See tests/test_pr10_multimodal_ingest_wiring.py — updated to check routes/chat.py.

logger = logging.getLogger(__name__)

# ── Module-level service globals (backward-compat only) ──────────────────────
# These start as None and are populated by bootstrap.lifecycle.lifespan when
# the application starts.  Legacy code that does:
#     from galaxy_gateway.app import websocket_manager
# continues to work because lifespan updates these at startup.
# New code should use galaxy_gateway.dependencies instead.
device_manager: Optional[Any] = None
message_handler: Optional[Any] = None
websocket_manager: Optional[Any] = None
task_orchestrator: Optional[Any] = None
openclawd_instance: Optional[Any] = None
llm_router_instance: Optional[Any] = None
nats_adapter: Optional[Any] = None
heartbeat_scheduler: Optional[Any] = None


# ============================================================================
# Route prefix validation helper (Bug 5 fix)
# ============================================================================

def _validate_router_prefix(router: Any, name: str) -> None:
    """Validate that a router has a proper URL prefix (Bug 5 fix).

    Routes under ``/api/`` MUST have a prefix to prevent accidental
    top-level path collisions.  Logs a warning if the prefix is missing.
    """
    # Safe access — not all routers expose .prefix (e.g. plain APIRouter)
    prefix: str = getattr(router, "prefix", "") or ""
    routes: list = getattr(router, "routes", [])
    if not prefix and routes:
        # Only warn for routers that have actual routes but no prefix
        logger.warning(
            "Router '%s' has no URL prefix — consider adding one to avoid path collisions",
            name,
        )


# ============================================================================
# FastAPI application — thin composition layer
# ============================================================================

app = FastAPI(
    title="Galaxy Gateway",
    description="跨平台分布式 Agent 网关",
    version="3.0.0",
    lifespan=lifespan,
)

# ── Middleware (Bug 6 — order is documented above; LIFO execution) ──────────
# CORSMiddleware registered FIRST → executes LAST on request path
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=get_cors_methods(),
    allow_headers=get_cors_headers(),
    max_age=86400,  # Bug 3 fix: cache preflight for 24 hours
)
# Bearer token auth (no-op unless GALAXY_AUTH_ENABLED=true)
app.add_middleware(BearerAuthMiddleware)
# Request ID assignment (Bug 7 fix: UUID-based)
app.add_middleware(RequestIdMiddleware)
# Security headers (Bug 8 fix: X-Content-Type-Options, X-Frame-Options, etc.)
app.add_middleware(SecurityHeadersMiddleware)


# ── REST routers (Bug 5 fix: validate prefixes) ─────────────────────────────
_routers = [
    (health_router, "health_router"),
    (devices_router, "devices_router"),
    (tasks_router, "tasks_router"),
    (sessions_router, "sessions_router"),
    (chat_router, "chat_router"),
    (llm_router, "llm_router"),
]

for _router, _name in _routers:
    _validate_router_prefix(_router, _name)
    app.include_router(_router)

# 接线(审计 KEEP-WIRE):/sync/status 跨设备同步质量诊断端点——模块一直存在
# 但从未被挂载(孤儿路由)。fastapi 缺失时模块自身优雅降级(router=None)。
try:
    from galaxy_gateway.routes.sync_status import router as _sync_status_router
    if _sync_status_router is not None:
        _validate_router_prefix(_sync_status_router, "sync_status_router")
        app.include_router(_sync_status_router)
        logger.debug("Sync status route mounted: GET /sync/status")
except (ImportError, ModuleNotFoundError, AttributeError) as _sync_exc:
    logger.warning("sync_status 路由挂载跳过: %s", _sync_exc)


# ── WebSocket endpoints (order-sensitive — must be registered after routers) ──
register_websocket_routes(app)


# ── Optional sub-service routers (may be absent in minimal deployments) ──────

# Helper: safely include an optional router with prefix validation
def _try_include_router(
    import_path: str,
    router_attr: str,
    log_msg: str,
    log_exc_msg: str,
) -> None:
    """Try to import and include a router; log on success or skip on failure."""
    try:
        mod = __import__(import_path, fromlist=[router_attr])
        router = getattr(mod, router_attr)
        if router is not None:
            _name = getattr(router, "name", router_attr)
            _validate_router_prefix(router, _name)
            app.include_router(router)
            logger.debug(log_msg)
    except (ImportError, ModuleNotFoundError, AttributeError) as _err:
        logger.debug(log_exc_msg, _err)


try:
    from core.routes.ai import create_router as _create_ai_router
    app.include_router(_create_ai_router(), tags=["ai-agents"])
    logger.debug("AI Agent 路由已挂载 (/api/v1/agents/*, /api/v1/ai/*)")
except (ImportError, ModuleNotFoundError, AttributeError) as _ai_err:
    logger.debug("AI Agent 路由挂载跳过: %s", _ai_err)

try:
    from galaxy_gateway.routes.linux_agent import router as _linux_agent_router
    _validate_router_prefix(_linux_agent_router, "linux_agent_router")
    app.include_router(_linux_agent_router)
    logger.debug("Linux Agent 路由已挂载 (/api/v1/agents/linux/*)")
except (ImportError, ModuleNotFoundError, AttributeError) as _la_err:
    logger.debug("Linux Agent 路由挂载跳过: %s", _la_err)

try:
    from galaxy_gateway.routes.sandbox import router as _sandbox_router
    _validate_router_prefix(_sandbox_router, "sandbox_router")
    app.include_router(_sandbox_router)
    logger.debug("Sandbox 路由已挂载 (/api/v1/agents/sandbox/*)")
except (ImportError, ModuleNotFoundError, AttributeError) as _sb_err:
    logger.debug("Sandbox 路由挂载跳过: %s", _sb_err)

try:
    from .gateway_service import router as _gateway_v5_router
    _validate_router_prefix(_gateway_v5_router, "gateway_v5_router")
    app.include_router(_gateway_v5_router, tags=["gateway-v5"])
    logger.debug("Gateway v5.0 routes mounted")
except (ImportError, ModuleNotFoundError, AttributeError) as _gw5_err:
    logger.debug("Gateway v5.0 routes not mounted (optional): %s", _gw5_err)  # PR-LOG-LEVEL: optional component → debug not error

try:
    from .api.config import router as _client_config_router
    _validate_router_prefix(_client_config_router, "client_config_router")
    app.include_router(_client_config_router)
    logger.debug("Client config discovery route mounted: GET /api/v1/config")
except (ImportError, ModuleNotFoundError, AttributeError) as _cfg_err:
    logger.debug("Client config route mount skipped: %s", _cfg_err)

try:
    from .api.pairing import router as _pairing_router
    _validate_router_prefix(_pairing_router, "pairing_router")
    app.include_router(_pairing_router)
    logger.debug("Device pairing routes mounted: /api/v1/pairing/*")
except (ImportError, ModuleNotFoundError, AttributeError) as _pair_err:
    logger.debug("Device pairing routes mount skipped: %s", _pair_err)


# ============================================================================
# Main entry point
# ============================================================================

def main() -> None:
    """Start the Galaxy Gateway with uvicorn."""
    import uvicorn

    try:
        from core.port_config import get_service_port
        _default_gw_port = str(get_service_port("gateway"))
    except (ImportError, ModuleNotFoundError, AttributeError):
        _default_gw_port = "8765"

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", _default_gw_port))

    tls_cert = os.getenv("GALAXY_TLS_CERT", "").strip()
    tls_key = os.getenv("GALAXY_TLS_KEY", "").strip()

    if tls_cert and tls_key:
        logger.info(
            "Starting Galaxy Gateway on %s:%s (TLS ENABLED, cert=%s)",
            host, port, tls_cert,
        )
        uvicorn.run(app, host=host, port=port, ssl_certfile=tls_cert, ssl_keyfile=tls_key)
    else:
        logger.info(
            "Starting Galaxy Gateway on %s:%s (TLS DISABLED — "
            "set GALAXY_TLS_CERT + GALAXY_TLS_KEY to enable HTTPS)",
            host, port,
        )
        uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
