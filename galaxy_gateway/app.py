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
"""

import logging
import os
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nodes.common.cors_config import get_cors_origins

# ── New sub-modules (extracted from this file) ──
from galaxy_gateway.bootstrap.lifecycle import lifespan
from galaxy_gateway.middleware import BearerAuthMiddleware  # re-exported for compat
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
# FastAPI application — thin composition layer
# ============================================================================

app = FastAPI(
    title="Galaxy Gateway",
    description="跨平台分布式 Agent 网关",
    version="3.0.0",
    lifespan=lifespan,
)

# ── Middleware ────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Bearer token auth (no-op unless GALAXY_AUTH_ENABLED=true)
app.add_middleware(BearerAuthMiddleware)


# ── REST routers ──────────────────────────────────────────────────────────────
app.include_router(health_router)
app.include_router(devices_router)
app.include_router(tasks_router)
app.include_router(sessions_router)
app.include_router(chat_router)
app.include_router(llm_router)

try:
    from galaxy_gateway.routes.android_vlm import router as android_vlm_router
    app.include_router(android_vlm_router)
    logger.info("Android VLM routes mounted (/api/v1/android/vlm/*)")
except Exception as _vlm_err:
    logger.warning("Android VLM route mount skipped: %s", _vlm_err)


# ── WebSocket endpoints (order-sensitive — must be registered after routers) ──
register_websocket_routes(app)


# ── Optional sub-service routers (may be absent in minimal deployments) ──────

try:
    from core.routes.ai import create_router as _create_ai_router
    app.include_router(_create_ai_router(), tags=["ai-agents"])
    logger.info("AI Agent 路由已挂载 (/api/v1/agents/*, /api/v1/ai/*)")
except Exception as _ai_err:
    logger.warning("AI Agent 路由挂载跳过: %s", _ai_err)

try:
    from galaxy_gateway.routes.linux_agent import router as _linux_agent_router
    app.include_router(_linux_agent_router)
    logger.info("Linux Agent 路由已挂载 (/api/v1/agents/linux/*)")
except Exception as _la_err:
    logger.warning("Linux Agent 路由挂载跳过: %s", _la_err)

try:
    from galaxy_gateway.routes.sandbox import router as _sandbox_router
    app.include_router(_sandbox_router)
    logger.info("Sandbox 路由已挂载 (/api/v1/agents/sandbox/*)")
except Exception as _sb_err:
    logger.warning("Sandbox 路由挂载跳过: %s", _sb_err)

try:
    from .gateway_service import router as _gateway_v5_router
    app.include_router(_gateway_v5_router, tags=["gateway-v5"])
    logger.info("Gateway v5.0 路由已挂载")
except Exception as _gw5_err:
    logger.warning("Gateway v5.0 路由挂载跳过: %s", _gw5_err)

try:
    from .api.config import router as _client_config_router
    app.include_router(_client_config_router)
    logger.info("Client config discovery route mounted: GET /api/v1/config")
except Exception as _cfg_err:
    logger.warning("Client config route mount skipped: %s", _cfg_err)


# ============================================================================
# Main entry point
# ============================================================================

def main():
    """Start the Galaxy Gateway with uvicorn."""
    import uvicorn

    try:
        from core.port_config import get_service_port
        _default_gw_port = str(get_service_port("gateway"))
    except Exception:
        _default_gw_port = "8765"

    host = os.getenv("HOST", "0.0.0.0")
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
