"""
galaxy_gateway/routes/websocket.py — WebSocket 路由兼容层

PR-GATEWAY-FIX: 提供 core/api_routes.py 所需的导出，
实际实现委托给 galaxy_gateway.websocket_handler。
"""

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
        "handler": "GatewayWSManager.handle_device_connection",
    },
    {
        "path": "/ws/master",
        "method": "WS",
        "auth": "MASTER_TOKEN",
        "description": "Master node WebSocket for multi-node federation",
        "handler": "GatewayWSManager.handle_master_connection",
    },
]

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
