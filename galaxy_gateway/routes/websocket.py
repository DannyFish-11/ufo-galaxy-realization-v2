"""
galaxy_gateway/routes/websocket.py — WebSocket endpoint registration.

WebSocket endpoints for the Galaxy Gateway.  Registration order matters:
more-specific routes MUST appear before generic catch-all routes so that
``/ws/android/*`` and ``/ws/device/*`` are not shadowed by ``/ws/{device_id}``.

Registration order:
  1. /ws/android/{device_id}   — primary Android path (android_bridge, AIP v3)
  2. /ws/android               — Android fallback path
  3. /ws/ufo3/{device_id}      — legacy UFO3 (disabled by default)
  4. /ws/device/{device_id}    — compat alias for /ws/android/{device_id}
  5. /ws/webrtc/{device_id}    — WebRTC signaling proxy
  6. /ws/{device_id}           — generic catch-all
  7. /ws                       — generic auto-ID catch-all
"""

import logging
import os
import uuid

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

# Set GALAXY_ENABLE_LEGACY_PROTOCOLS=true to re-enable legacy WS paths such as
# /ws/ufo3.  By default these paths are disabled to enforce the unified Gateway
# entry point (AIP v3 via /ws/device/{id} or /ws/android/{id}).
_LEGACY_PROTOCOLS_ENABLED = (
    os.environ.get("GALAXY_ENABLE_LEGACY_PROTOCOLS", "false").lower() == "true"
)

if _LEGACY_PROTOCOLS_ENABLED:
    logger.warning(
        "GALAXY_ENABLE_LEGACY_PROTOCOLS=true — legacy WS paths (/ws/ufo3) are ENABLED. "
        "This is for backward compatibility only. Disable in production."
    )


# ---------------------------------------------------------------------------
# Internal Android WS handler (also exported for tests)
# ---------------------------------------------------------------------------

async def _handle_android_ws(websocket: WebSocket, device_id: str) -> None:
    """Internal handler used by all Android WS endpoints.

    Routes every message through ``android_bridge.handle_message()`` so that
    AIP v3 protocol types, device registration, heartbeat, and task lifecycle
    are all handled by the single gateway bridge rather than the generic
    WebSocketManager.

    All incoming messages are first normalised to AIP v3 via
    ``parse_message_compat`` before being forwarded to the bridge.  This means
    legacy clients (AIP/1.0, 2.0) are silently upgraded to v3 at the WS layer;
    no legacy-specific parsing occurs inside the bridge itself.
    """
    from galaxy_gateway.android_bridge import android_bridge as _android_bridge
    from galaxy_gateway.protocol.compat import normalise_to_v3_dict as _normalise

    await websocket.accept()
    logger.info("Android device connected via android_bridge: device_id=%s", device_id)

    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = _normalise(data)
            except Exception:
                logger.warning(
                    "Android [%s]: failed to parse/normalise message, skipping", device_id
                )
                continue

            response = await _android_bridge.handle_message(websocket, message)
            if response:
                await websocket.send_json(response)

    except WebSocketDisconnect:
        logger.info("Android device disconnected: device_id=%s", device_id)
        await _android_bridge.disconnect_device(device_id)
    except Exception as exc:
        logger.error(
            "Android WS error: device_id=%s error=%s", device_id, exc, exc_info=True
        )
        await _android_bridge.disconnect_device(device_id)


# ---------------------------------------------------------------------------
# Route registration — called from app.py after app creation
# ---------------------------------------------------------------------------

def register_websocket_routes(app: FastAPI) -> None:
    """Register all WebSocket routes on the given FastAPI app.

    Must be called after the app object is created.  Registration order is
    significant — more-specific paths must be registered first.
    """

    @app.websocket("/ws/android/{device_id}")
    async def websocket_android_primary(websocket: WebSocket, device_id: str):
        """Primary Android WebSocket path — routed through android_bridge (AIP v3)."""
        logger.info("Primary path /ws/android/ used for device %s", device_id)
        await _handle_android_ws(websocket, device_id)

    @app.websocket("/ws/android")
    async def websocket_android(websocket: WebSocket, device_id: str = Query(None)):
        """Android fallback WebSocket path — routed through android_bridge (AIP v3)."""
        if not device_id:
            device_id = str(uuid.uuid4())
        logger.info("Fallback path /ws/android used, device_id=%s", device_id)
        await _handle_android_ws(websocket, device_id)

    @app.websocket("/ws/ufo3/{device_id}")
    async def websocket_ufo3(websocket: WebSocket, device_id: str):
        """Legacy UFO3 WebSocket path.

        Disabled by default.  Set ``GALAXY_ENABLE_LEGACY_PROTOCOLS=true`` to
        allow connections on this path.  When disabled the connection is
        rejected with an explicit error so clients can identify the cause.

        When enabled, routes through the same android_bridge pipeline as
        ``/ws/android/{device_id}`` with all incoming messages normalised to
        AIP v3 via ``parse_message_compat``.
        """
        if not _LEGACY_PROTOCOLS_ENABLED:
            logger.warning(
                "Rejected legacy /ws/ufo3/ connection for device %s. "
                "Set GALAXY_ENABLE_LEGACY_PROTOCOLS=true to re-enable, "
                "or update the client to use /ws/device/%s (AIP v3).",
                device_id, device_id,
            )
            await websocket.accept()
            import json as _json
            await websocket.send_text(_json.dumps({
                "error": "legacy_path_disabled",
                "message": (
                    "The /ws/ufo3 path is disabled. "
                    "Use /ws/device/<device_id> (AIP v3) or set "
                    "GALAXY_ENABLE_LEGACY_PROTOCOLS=true to re-enable."
                ),
                "action": "reconnect",
                "recommended_path": f"/ws/device/{device_id}",
            }))
            await websocket.close(
                code=1008,
                reason="Legacy path disabled. Use /ws/device/<id> with AIP v3.",
            )
            return
        logger.info("Legacy path /ws/ufo3/ used for device %s", device_id)
        await _handle_android_ws(websocket, device_id)

    @app.websocket("/ws/device/{device_id}")
    async def websocket_device(websocket: WebSocket, device_id: str):
        """Android device WebSocket path — compat alias for /ws/android/{device_id}."""
        logger.info("Compat path /ws/device/ used for device %s", device_id)
        await _handle_android_ws(websocket, device_id)

    @app.websocket("/ws/webrtc/{device_id}")
    async def webrtc_signaling_proxy(websocket: WebSocket, device_id: str):
        """WebSocket passthrough — proxy Android signaling to Node_95.

        Accepts a WebSocket connection from an Android client and relays all
        signaling messages (Offer / Answer / ICE Candidate) to the Node_95
        ``/signaling/{device_id}`` endpoint, forwarding responses back.

        Closes with code 1011 (server error / 503-equivalent) when Node_95 is
        unreachable so the client can fall back gracefully.
        """
        from galaxy_gateway.webrtc_proxy import proxy_webrtc_signaling
        await proxy_webrtc_signaling(websocket, device_id)

    @app.websocket("/ws/{device_id}")
    async def websocket_endpoint(websocket: WebSocket, device_id: str):
        """Generic device WebSocket endpoint (catch-all for non-Android paths)."""
        wsm = websocket.app.state.websocket_manager
        await wsm.handle_connection(websocket, device_id)

    @app.websocket("/ws")
    async def websocket_endpoint_auto(
        websocket: WebSocket, device_id: str = Query(None)
    ):
        """Auto-assign device-ID WebSocket endpoint."""
        if not device_id:
            device_id = str(uuid.uuid4())
        wsm = websocket.app.state.websocket_manager
        await wsm.handle_connection(websocket, device_id)
