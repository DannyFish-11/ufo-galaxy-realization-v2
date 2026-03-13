"""
WebRTC Signaling Gateway Proxy
================================

Provides a gateway-level adapter that routes Android signaling messages to
Node_95_WebRTC_Receiver, so Android clients need only know the main gateway
address rather than Node_95 directly.

Public helpers
--------------
* ``get_webrtc_endpoint_info()``  — returns endpoint metadata for REST callers.
* ``proxy_webrtc_signaling()``    — async WS passthrough handler for FastAPI routes.
* ``check_node95_reachable()``    — lightweight reachability probe.

Environment variables
---------------------
NODE_95_URL              HTTP base URL of Node_95_WebRTC_Receiver (default: http://localhost:8095)
GATEWAY_URL              HTTP base URL of this gateway service      (default: http://localhost:8765)
GALAXY_STUN_URLS         Comma-separated STUN server URLs (e.g. stun:stun.l.google.com:19302)
GALAXY_TURN_URLS         Comma-separated TURN server URLs (e.g. turn:turn.example.com:3478)
GALAXY_TURN_USERNAME     TURN server credential username
GALAXY_TURN_CREDENTIAL   TURN server credential password
GALAXY_TAILSCALE_ENABLED true/1/yes to signal that Tailscale networking is active
GALAXY_TAILSCALE_HOST    Tailscale tailnet hostname or MagicDNS name for this gateway node
GALAXY_TAILSCALE_TAG     Optional Tailscale ACL tag for this node
"""

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

import httpx
import websockets
from fastapi import WebSocket, WebSocketDisconnect
from core.port_config import get_service_port, get_node_port

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_node95_url() -> str:
    """Return current Node_95 base URL from environment."""
    return os.getenv("NODE_95_URL", f"http://localhost:{get_node_port('Node_95_WebRTC_Receiver')}").rstrip("/")


def _get_gateway_url() -> str:
    """Return current Gateway base URL from environment."""
    return os.getenv("GATEWAY_URL", f"http://localhost:{get_service_port('state_machine')}").rstrip("/")


def _http_to_ws(url: str) -> str:
    """Convert an http(s):// URL to ws(s)://."""
    return url.replace("https://", "wss://").replace("http://", "ws://")


def _get_ice_servers() -> List[Dict[str, Any]]:
    """
    Build an ICE server list from environment variables.

    Returns a list in the format expected by RTCPeerConnection.iceServers:
    [{"urls": [...], "username": "...", "credential": "..."}, ...]

    When no STUN/TURN env vars are set an empty list is returned so that
    callers can detect the absence of configuration and fall back to browser
    defaults.
    """
    servers: List[Dict[str, Any]] = []

    raw_stun = os.getenv("GALAXY_STUN_URLS", "").strip()
    if raw_stun:
        stun_urls = [u.strip() for u in raw_stun.split(",") if u.strip()]
        if stun_urls:
            servers.append({"urls": stun_urls})

    raw_turn = os.getenv("GALAXY_TURN_URLS", "").strip()
    if raw_turn:
        turn_urls = [u.strip() for u in raw_turn.split(",") if u.strip()]
        if turn_urls:
            entry: Dict[str, Any] = {"urls": turn_urls}
            username = os.getenv("GALAXY_TURN_USERNAME", "").strip()
            credential = os.getenv("GALAXY_TURN_CREDENTIAL", "").strip()
            if username:
                entry["username"] = username
            if credential:
                entry["credential"] = credential
            servers.append(entry)

    return servers


def _get_tailscale_info() -> Optional[Dict[str, Any]]:
    """
    Return Tailscale metadata when Tailscale is configured.

    Returns None when Tailscale is not enabled, or a dict with available
    metadata fields when it is.
    """
    enabled = os.getenv("GALAXY_TAILSCALE_ENABLED", "").strip().lower() in ("1", "true", "yes")
    if not enabled:
        return None

    info: Dict[str, Any] = {"enabled": True}

    host = os.getenv("GALAXY_TAILSCALE_HOST", "").strip()
    if host:
        info["host"] = host

    tag = os.getenv("GALAXY_TAILSCALE_TAG", "").strip()
    if tag:
        info["tag"] = tag

    return info


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def check_node95_reachable() -> bool:
    """
    Probe Node_95 /health endpoint.

    Returns True when Node_95 responds with HTTP 200; False otherwise.
    """
    url = _get_node95_url()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{url}/health")
            return resp.status_code == 200
    except Exception:
        return False


def get_webrtc_endpoint_info() -> Dict[str, Any]:
    """
    Return signaling endpoint metadata that Android clients can use.

    Callers may choose to connect to Node_95 directly (``node95_url`` +
    ``ws_signaling_path``) or to route through the gateway
    (``gateway_ws_path``).

    When STUN/TURN servers or Tailscale are configured their metadata is
    included under ``ice_servers`` and ``tailscale`` keys respectively so
    that clients can immediately apply the correct ICE configuration.
    """
    node95_url = _get_node95_url()
    gateway_url = _get_gateway_url()
    info: Dict[str, Any] = {
        "node95_url": node95_url,
        "ws_signaling_path": "/signaling/{device_id}",
        "gateway_ws_url": gateway_url,
        "gateway_ws_path": "/ws/webrtc/{device_id}",
    }

    ice_servers = _get_ice_servers()
    if ice_servers:
        info["ice_servers"] = ice_servers

    tailscale = _get_tailscale_info()
    if tailscale is not None:
        info["tailscale"] = tailscale

    return info


async def proxy_webrtc_signaling(client_ws: WebSocket, device_id: str) -> None:
    """
    Proxy WebRTC signaling between an Android client and Node_95.

    Accepts the inbound WebSocket from the Android client, opens a WebSocket
    connection to ``NODE_95_URL/signaling/{device_id}``, then relays messages
    in both directions until either side disconnects.

    If Node_95 is unreachable the connection is closed with code 1011 (an
    application-level error analogous to HTTP 503).
    """
    await client_ws.accept()

    node95_ws_url = f"{_http_to_ws(_get_node95_url())}/signaling/{device_id}"
    logger.info("WebRTC proxy: connecting to Node_95 at %s", node95_ws_url)

    try:
        async with websockets.connect(node95_ws_url, open_timeout=5) as node_ws:
            logger.info(
                "WebRTC proxy: tunnel established for device %s", device_id
            )

            async def _client_to_node() -> None:
                """Forward messages from Android client → Node_95."""
                try:
                    while True:
                        data = await client_ws.receive_text()
                        await node_ws.send(data)
                except (WebSocketDisconnect, Exception) as exc:
                    logger.debug(
                        "WebRTC proxy [%s] client→node95 stopped: %s",
                        device_id, exc,
                    )

            async def _node_to_client() -> None:
                """Forward messages from Node_95 → Android client."""
                try:
                    async for message in node_ws:
                        await client_ws.send_text(
                            message if isinstance(message, str)
                            else message.decode()
                        )
                except (WebSocketDisconnect, Exception) as exc:
                    logger.debug(
                        "WebRTC proxy [%s] node95→client stopped: %s",
                        device_id, exc,
                    )

            tasks = [
                asyncio.create_task(_client_to_node()),
                asyncio.create_task(_node_to_client()),
            ]
            _done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    except Exception as exc:
        logger.warning(
            "WebRTC proxy: Node_95 unreachable for device %s — %s",
            device_id, exc,
        )
        try:
            await client_ws.close(code=1011, reason="Node_95 WebRTC Receiver unavailable")
        except Exception:
            pass
