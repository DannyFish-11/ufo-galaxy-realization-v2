"""
galaxy_gateway/routes/websocket.py — WebSocket endpoint registration.

# ============================================================================
# CANONICAL DEVICE INGRESS AUTHORITY
# ============================================================================
# The sole canonical device ingress path for this gateway is:
#
#   /ws/device/{device_id}
#
# All device connections MUST enter the system through this path for primary
# production use.  All other device-facing WebSocket paths in this file are
# explicitly non-canonical and are classified below.
#
# Path authority classifications:
#   /ws/device/{device_id}    — [CANONICAL]        sole canonical device ingress (AIP v3)
#   /ws/android/{device_id}   — [COMPAT]           Android-legacy compat path; delegates to canonical ingress pipeline
#   /ws/android               — [COMPAT]           Android fallback compat path; delegates to canonical ingress pipeline
#   /ws/ufo3/{device_id}      — [LEGACY-DISABLED]  UFO3 legacy path; disabled by default
#   /ws/webrtc/{device_id}    — [MEDIA]            WebRTC signaling proxy; non-device-mainline, media-specific only
#   /ws/{device_id}           — [DEPRECATED]       generic catch-all; non-primary, do not use for new clients
#   /ws                       — [DEBUG]            auto-assign debug path; not for production device ingress
#
# Registration order matters: more-specific routes MUST appear before generic
# catch-all routes so that /ws/device/* and /ws/android/* are not shadowed
# by /ws/{device_id}.
# ============================================================================
"""

import logging
import os
import uuid

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

# ============================================================================
# CANONICAL_DEVICE_INGRESS_AUTHORITY
# ============================================================================
# This module owns the sole canonical device ingress for the Galaxy Gateway.
# The canonical path is /ws/device/{device_id} (see route below).
# All other device-facing WebSocket paths are non-canonical (compat, deprecated,
# debug, or legacy-disabled) and must not be treated as peer-level ingress.
# ============================================================================
CANONICAL_DEVICE_INGRESS_AUTHORITY = (
    "galaxy_gateway.routes.websocket: CANONICAL device ingress = /ws/device/{device_id} "
    "(AIP v3). All other device WS paths are compat/deprecated/debug/legacy-disabled."
)

# Set GALAXY_ENABLE_LEGACY_PROTOCOLS=true to re-enable legacy WS paths such as
# /ws/ufo3.  By default these paths are disabled to enforce the unified Gateway
# entry point (AIP v3 via /ws/device/{id}).
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
        """[COMPAT] Android-legacy compatibility path.

        Delegates to the canonical device ingress pipeline (android_bridge, AIP v3).
        This path exists for backward compatibility with Android clients that have
        not yet migrated to the canonical ingress at /ws/device/{device_id}.

        NOT the canonical device ingress — use /ws/device/{device_id} instead.
        """
        logger.info(
            "Compat path /ws/android/ used for device %s — "
            "canonical ingress is /ws/device/{device_id}",
            device_id,
        )
        await _handle_android_ws(websocket, device_id)

    @app.websocket("/ws/android")
    async def websocket_android(websocket: WebSocket, device_id: str = Query(None)):
        """[COMPAT] Android fallback compatibility path.

        Delegates to the canonical device ingress pipeline (android_bridge, AIP v3).
        This path exists for backward compatibility with Android clients that have
        not yet migrated to the canonical ingress at /ws/device/{device_id}.

        NOT the canonical device ingress — use /ws/device/{device_id} instead.
        """
        if not device_id:
            device_id = str(uuid.uuid4())
        logger.info(
            "Compat path /ws/android used, device_id=%s — "
            "canonical ingress is /ws/device/{device_id}",
            device_id,
        )
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
        """[CANONICAL] Sole canonical device ingress for the Galaxy Gateway.

        This is the authoritative entry point for all production device connections.
        All device traffic MUST use this path.  Messages are routed through the
        android_bridge (AIP v3) pipeline for protocol normalisation, registration,
        heartbeat, and task lifecycle.

        All other device-facing WebSocket paths (/ws/android, /ws/{device_id}, /ws,
        /ws/ufo3) are non-canonical and must not be treated as peer-level ingress.
        """
        logger.info("Canonical ingress /ws/device/ accepted device %s", device_id)
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
        """[DEPRECATED] Generic catch-all WebSocket endpoint.

        This path is non-primary and must not be used for new device clients.
        Exists solely to prevent connection failures from legacy clients that
        do not use the canonical ingress at /ws/device/{device_id}.

        New device integrations MUST use /ws/device/{device_id} instead.
        """
        wsm = websocket.app.state.websocket_manager
        await wsm.handle_connection(websocket, device_id)

    @app.websocket("/ws")
    async def websocket_endpoint_auto(
        websocket: WebSocket, device_id: str = Query(None)
    ):
        """[DEBUG] Auto-assign debug WebSocket endpoint.

        Not for production device ingress.  This path auto-assigns a device ID
        and is intended for development/debugging only.  It does NOT participate
        in the canonical ingress pipeline.

        Production devices MUST use /ws/device/{device_id} instead.
        """
        if not device_id:
            device_id = str(uuid.uuid4())
        wsm = websocket.app.state.websocket_manager
        await wsm.handle_connection(websocket, device_id)
