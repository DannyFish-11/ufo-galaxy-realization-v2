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

import json
import logging
import os
import time
import uuid
from typing import Literal, TypedDict

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


IngressClassification = Literal[
    "canonical",
    "compat",
    "legacy-disabled",
    "media",
    "deprecated",
    "debug",
]
"""Authority classification for each gateway websocket surface.

- canonical: sole production ingress authority for device mainline traffic
- compat: migration/compatibility ingress that still delegates to canonical pipeline
- legacy-disabled: historical ingress that is disabled by default
- media: media/signaling-only websocket surface (not device-mainline ingress)
- deprecated: old generic ingress retained for backward compatibility only
- debug: development/debug websocket surface, non-production
"""


class DeviceWsIngressSurface(TypedDict):
    """Machine-readable websocket route authority metadata.

    `android_bridge_ingress=True` means the route is expected to delegate into
    the android_bridge device-mainline pipeline.
    """

    path: str
    classification: IngressClassification
    android_bridge_ingress: bool

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

DEVICE_WS_INGRESS_SURFACE_REGISTRY: tuple[DeviceWsIngressSurface, ...] = (
    {
        "path": "/ws/device/{device_id}",
        "classification": "canonical",
        "android_bridge_ingress": True,
    },
    {
        "path": "/ws/android/{device_id}",
        "classification": "compat",
        "android_bridge_ingress": True,
    },
    {
        "path": "/ws/android",
        "classification": "compat",
        "android_bridge_ingress": True,
    },
    {
        "path": "/ws/ufo3/{device_id}",
        "classification": "legacy-disabled",
        "android_bridge_ingress": True,
    },
    {
        "path": "/ws/webrtc/{device_id}",
        "classification": "media",
        "android_bridge_ingress": False,
    },
    {
        "path": "/ws/{device_id}",
        "classification": "deprecated",
        "android_bridge_ingress": False,
    },
    {"path": "/ws", "classification": "debug", "android_bridge_ingress": False},
)

_VALID_ANDROID_BRIDGE_INGRESS_CLASSIFICATIONS = frozenset(
    entry["classification"]
    for entry in DEVICE_WS_INGRESS_SURFACE_REGISTRY
    if entry["android_bridge_ingress"]
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

async def _handle_android_ws(
    websocket: WebSocket,
    device_id: str,
    *,
    ingress_path: str = "/ws/device/{device_id}",
    ingress_classification: str = "canonical",
) -> None:
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

    if ingress_classification not in _VALID_ANDROID_BRIDGE_INGRESS_CLASSIFICATIONS:
        raise ValueError(
            f"Unsupported ingress_classification={ingress_classification!r} for android_bridge ingress. "
            f"Valid classifications for android_bridge ingress routes: "
            f"{sorted(_VALID_ANDROID_BRIDGE_INGRESS_CLASSIFICATIONS)}"
        )

    await websocket.accept()
    is_canonical_ingress = ingress_classification == "canonical"
    if not is_canonical_ingress:
        logger.warning(
            "Non-canonical WS ingress used: path=%s classification=%s device_id=%s; "
            "canonical ingress is /ws/device/{device_id}",
            ingress_path,
            ingress_classification,
            device_id,
        )
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

            # Ingress boundary context:
            # - _ingress_connection_device_id: canonical WS path identity
            # - _ingress_transport_token: optional token from WS query (?token=...)
            # Registration handlers can validate identity/auth without conflating
            # mere socket connectivity with effective authenticated participation.
            message["_ingress_connection_device_id"] = device_id
            message["_ingress_ws_path"] = ingress_path
            message["_ingress_ws_classification"] = ingress_classification
            message["_ingress_is_canonical"] = is_canonical_ingress
            if "_ingress_transport_token" not in message:
                _ws_query_token = websocket.query_params.get("token")
                if _ws_query_token:
                    message["_ingress_transport_token"] = _ws_query_token

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
        await _handle_android_ws(
            websocket,
            device_id,
            ingress_path="/ws/android/{device_id}",
            ingress_classification="compat",
        )

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
        await _handle_android_ws(
            websocket,
            device_id,
            ingress_path="/ws/android",
            ingress_classification="compat",
        )

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
        await _handle_android_ws(
            websocket,
            device_id,
            ingress_path="/ws/ufo3/{device_id}",
            ingress_classification="legacy-disabled",
        )

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
        await _handle_android_ws(
            websocket,
            device_id,
            ingress_path="/ws/device/{device_id}",
            ingress_classification="canonical",
        )

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

    # ── Desktop Presence WebSocket (for Electron 3-state GUI) ──
    @app.websocket("/ws/desktop-presence")
    async def websocket_desktop_presence(websocket: WebSocket):
        """Desktop presence WebSocket — for the Electron 3-state GUI.

        Pushes phase-change events (silent/liminal/manifest) to the desktop
        overlay so it can animate transitions.

        PR-PHASE-PUSH: Now actively pushes phase changes via state_event_bus
        subscription instead of only responding to client requests.
        """
        await websocket.accept()
        logger.info("Desktop presence WebSocket connected")

        from core.desktop_presence_runtime import get_desktop_presence_runtime
        dpr = get_desktop_presence_runtime()

        # PR-PHASE-PUSH: Active push — subscribe to state_event_bus phase events
        _push_task = None
        _stop_event = asyncio.Event()

        async def _phase_pusher():
            """Listen for phase-change events and push to WebSocket."""
            try:
                from core.state_event_bus import subscribe

                queue = asyncio.Queue()

                def _on_phase_event(event_type, payload):
                    asyncio.get_event_loop().call_soon_threadsafe(
                        queue.put_nowait, (event_type, payload)
                    )

                # Subscribe to all three phase events
                for et_name in ("PHASE_SILENT", "PHASE_LIMINAL", "PHASE_MANIFEST"):
                    try:
                        subscribe(et_name, _on_phase_event)
                    except Exception:
                        pass

                while not _stop_event.is_set():
                    try:
                        et_name, payload = await asyncio.wait_for(queue.get(), timeout=1.0)
                        phase = et_name.replace("PHASE_", "").lower()
                        # PR-AIPV3-PHASE: Push AIP v3 STATE_EVENT format
                        # (backward-compatible: also includes legacy phase_change fields)
                        await websocket.send_text(json.dumps({
                            "type": "state_event",
                            "event_category": "phase",
                            "event_action": phase,
                            "device_id": "desktop_presence",
                            "timestamp": int(time.time() * 1000),
                            "reason": payload.get("reason", "") if payload else "",
                            "result": payload.get("result") if payload else None,
                            "_aip_version": "3.0",
                            # Legacy backward-compatible fields
                            "phase": phase,
                        }))
                    except asyncio.TimeoutError:
                        continue
                    except Exception:
                        break
            except Exception:
                pass  # state_event_bus not available — fall back to request/response

        _push_task = asyncio.create_task(_phase_pusher())

        try:
            while True:
                data = await websocket.receive_text()
                msg = json.loads(data) if data.startswith("{") else {"type": "ping"}

                if msg.get("type") == "get_phase":
                    phase = dpr.get_current_phase() if hasattr(dpr, "get_current_phase") else "silent"
                    # PR-AIPV3-PHASE: AIP v3 STATE_EVENT format with legacy fallback
                    await websocket.send_text(json.dumps({
                        "type": "state_event",
                        "event_category": "phase",
                        "event_action": phase,
                        "device_id": "desktop_presence",
                        "timestamp": int(time.time() * 1000),
                        "_aip_version": "3.0",
                        "phase": phase,  # legacy backward-compatible
                    }))
                else:
                    phase = dpr.get_current_phase() if hasattr(dpr, "get_current_phase") else "silent"
                    await websocket.send_text(json.dumps({
                        "type": "heartbeat",
                        "phase": phase,
                        "timestamp": time.time(),
                    }))
        except WebSocketDisconnect:
            logger.info("Desktop presence WebSocket disconnected")
        except Exception as exc:
            logger.debug("Desktop presence WS error: %s", exc)
        finally:
            _stop_event.set()
            if _push_task and not _push_task.done():
                _push_task.cancel()
