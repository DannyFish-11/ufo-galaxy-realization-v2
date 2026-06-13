"""
galaxy_gateway/routes/websocket.py — WebSocket 路由兼容层

PR-GATEWAY-FIX: 提供 core/api_routes.py 所需的导出，
实际实现委托给 galaxy_gateway.websocket_handler。
"""

import logging

logger = logging.getLogger(__name__)

try:
    from galaxy_gateway.websocket_handler import (
        GatewayWSManager,
        parse_message_strict,
        handle_device_message,
        register_device_ws,
        unregister_device_ws,
    )
except ImportError:
    # Fallback stubs if websocket_handler is not available
    GatewayWSManager = None
    parse_message_strict = None
    handle_device_message = None
    register_device_ws = None
    unregister_device_ws = None

# ── Constants required by core/api_routes.py ──

CANONICAL_DEVICE_INGRESS_AUTHORITY = (
    "galaxy_gateway/routes/websocket.py is the canonical WebSocket device ingress. "
    "All Android Agent and cross-device WebSocket connections MUST enter through "
    "/ws/device/{device_id} handled by this module."
)

DEVICE_WS_INGRESS_SURFACE_REGISTRY = [
    {
        "path": "/ws/device/{device_id}",
        "method": "WS",
        "auth": "AIP_TOKEN + device_cert",
        "description": "Canonical WebSocket ingress for Android Agent and IoT devices",
        "handler": "_handle_android_ws",
        "classification": "canonical",
    },
    {
        "path": "/ws/android/{device_id}",
        "method": "WS",
        "auth": "AIP_TOKEN",
        "description": "Legacy Android ingress (path param) — delegates to canonical handler",
        "handler": "_handle_android_ws",
        "classification": "compat",
    },
    {
        "path": "/ws/android",
        "method": "WS",
        "auth": "AIP_TOKEN",
        "description": "Legacy Android ingress (query param) — delegates to canonical handler",
        "handler": "_handle_android_ws",
        "classification": "compat",
    },
    {
        "path": "/ws/master",
        "method": "WS",
        "auth": "MASTER_TOKEN",
        "description": "Master node WebSocket for multi-node federation",
        "handler": "GatewayWSManager.handle_master_connection",
        "classification": "internal",
    },
]


# ── Canonical Android/device WebSocket handler ──

async def _handle_android_ws(
    websocket,
    device_id: str,
    *,
    ingress_path: str = "/ws/device/{device_id}",
    ingress_classification: str = "canonical",
):
    """Canonical device WebSocket session loop.

    Accepts the connection, then pumps inbound JSON messages through
    :class:`~galaxy_gateway.android_bridge.AndroidBridge` and writes the
    bridge's responses back to the socket. All ingress surfaces (canonical
    and compat) converge on this single handler so message handling and
    ingress accounting cannot diverge per route.
    """
    from fastapi import WebSocketDisconnect
    from galaxy_gateway.android_bridge import android_bridge

    await websocket.accept()
    logger.info(
        "device ws connected: device_id=%s ingress=%s (%s)",
        device_id, ingress_path, ingress_classification,
    )
    try:
        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict):
                continue
            if device_id:
                message.setdefault("device_id", device_id)
            message.setdefault("_ingress_path", ingress_path)
            message.setdefault("_ingress_classification", ingress_classification)
            response = await android_bridge.handle_message(websocket, message)
            if response is not None:
                await websocket.send_json(response)
    except WebSocketDisconnect:
        logger.info("device ws disconnected: device_id=%s", device_id)
    except Exception as exc:
        logger.warning("device ws error for %s: %s", device_id, exc)
    finally:
        if device_id:
            try:
                await android_bridge.disconnect_device(device_id)
            except Exception as exc:
                logger.debug("device ws disconnect cleanup failed: %s", exc)


def register_websocket_routes(app) -> None:
    """Register the canonical and compat device WebSocket ingress routes.

    PR-25: exactly one canonical ingress (``/ws/device/{device_id}``); the
    legacy ``/ws/android`` surfaces remain available but are classified as
    compat and delegate to the same handler.
    """
    from fastapi import WebSocket

    @app.websocket("/ws/device/{device_id}")
    async def canonical_device_ws(websocket: WebSocket, device_id: str):
        # Resolved via module namespace so tests can monkeypatch the handler.
        await _resolve_android_ws_handler()(
            websocket,
            device_id,
            ingress_path="/ws/device/{device_id}",
            ingress_classification="canonical",
        )

    @app.websocket("/ws/android/{device_id}")
    async def compat_android_path_ws(websocket: WebSocket, device_id: str):
        await _resolve_android_ws_handler()(
            websocket,
            device_id,
            ingress_path="/ws/android/{device_id}",
            ingress_classification="compat",
        )

    @app.websocket("/ws/android")
    async def compat_android_query_ws(websocket: WebSocket):
        device_id = websocket.query_params.get("device_id", "")
        await _resolve_android_ws_handler()(
            websocket,
            device_id,
            ingress_path="/ws/android",
            ingress_classification="compat",
        )


def _resolve_android_ws_handler():
    """Late-bind the handler from this module so monkeypatching works."""
    import galaxy_gateway.routes.websocket as _self
    return _self._handle_android_ws

# ── WebSocket endpoint factory (for FastAPI) ──

def create_device_websocket_routes(app, service_manager=None):
    """Register WebSocket endpoints on the FastAPI app."""
    from fastapi import WebSocket, WebSocketDisconnect

    @app.websocket("/ws/device/{device_id}")
    async def device_ws_endpoint(websocket: WebSocket, device_id: str):
        await websocket.accept()
        if GatewayWSManager is not None:
            manager = GatewayWSManager()
            await manager.handle_device_connection(websocket, device_id)
        else:
            await websocket.close(code=1011, reason="GatewayWSManager not available")

    @app.websocket("/ws/master")
    async def master_ws_endpoint(websocket: WebSocket):
        await websocket.accept()
        if GatewayWSManager is not None:
            manager = GatewayWSManager()
            await manager.handle_master_connection(websocket)
        else:
            await websocket.close(code=1011, reason="GatewayWSManager not available")
