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
NODE_95_URL   HTTP base URL of Node_95_WebRTC_Receiver (default: http://localhost:8095)
GATEWAY_URL   HTTP base URL of this gateway service      (default: http://localhost:8000)
"""

import asyncio
import logging
import os
from typing import Dict, Any

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
    """
    node95_url = _get_node95_url()
    gateway_url = _get_gateway_url()
    return {
        "node95_url": node95_url,
        "ws_signaling_path": "/signaling/{device_id}",
        "gateway_ws_url": gateway_url,
        "gateway_ws_path": "/ws/webrtc/{device_id}",
    }


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
