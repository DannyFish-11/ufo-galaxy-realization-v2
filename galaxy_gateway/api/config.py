"""
Client Configuration Discovery Endpoint
========================================

Exposes ``GET /api/v1/config`` so that Android (and other) clients can
bootstrap their connection settings from the server instead of relying on
hard-coded local configuration.

Response fields
---------------
ws_base : str
    WebSocket base URL of this gateway (``ws://`` or ``wss://``).
    Example: ``"ws://192.168.1.10:8765"``

rest_base : str
    HTTP/REST base URL of this gateway.
    Example: ``"http://192.168.1.10:8765"``

ws_paths : list[str]
    Ordered list of WebSocket paths the client should try, from most
    preferred to least.  Replace the ``{id}`` placeholder with the actual
    device identifier at connection time.
    Example: ``["/ws/device/{id}", "/ws/android/{id}", "/ws/android"]``

webrtc_gateway_ws_path : str
    WebSocket path for WebRTC signaling through the gateway.
    Replace ``{id}`` with the device identifier.
    Example: ``"/ws/webrtc/{id}"``

stun_servers : list[str]
    STUN server URL(s) to populate ``RTCPeerConnection.iceServers``.
    Falls back to a well-known Google STUN server when
    ``GALAXY_STUN_URLS`` is not set.
    Example: ``["stun:stun.l.google.com:19302"]``

turn_servers : list[dict]
    TURN server objects in the format::

        {"urls": "turn:host:port", "username": "...", "credential": "..."}

    Empty list when TURN is not configured (``GALAXY_TURN_URLS`` not set).
    Clients *must not* crash when this list is empty.

transport_priority : list[str]
    Ordered transport preference.  Clients should probe each transport in
    order and use the first reachable one.
    Example: ``["tailscale", "intranet", "internet"]``

feature_flags : dict
    Boolean feature toggles that the client should respect.
    Example: ``{"tailscale_enabled": false, "use_gateway_for_webrtc": true}``

Environment variables
---------------------
GATEWAY_URL
    HTTP base URL of this gateway (used for ``rest_base`` and deriving
    ``ws_base``).  Default: ``http://localhost:8765``.
GALAXY_STUN_URLS
    Comma-separated STUN URLs.
    Default: ``stun:stun.l.google.com:19302``.
GALAXY_TURN_URLS
    Comma-separated TURN URLs.  Omit to return an empty ``turn_servers``.
GALAXY_TURN_USERNAME
    Username for all TURN entries.
GALAXY_TURN_CREDENTIAL
    Credential/password for all TURN entries.
GALAXY_TAILSCALE_ENABLED
    Set to ``1``, ``true``, or ``yes`` to mark Tailscale as available.
GALAXY_TRANSPORT_PRIORITY
    Comma-separated transport priority list.
    Default: ``tailscale,intranet,internet``.
"""

import logging
import os
from typing import Any, Dict, List

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["client-config"])

# ---------------------------------------------------------------------------
# Internal helpers (all read env at call-time so tests can patch os.environ)
# ---------------------------------------------------------------------------

_DEFAULT_GATEWAY_URL = "http://localhost:9000"
_DEFAULT_STUN = "stun:stun.l.google.com:19302"
_DEFAULT_TRANSPORT_PRIORITY = ["tailscale", "intranet", "internet"]

_WS_CANONICAL_PATH = "/ws/device/{id}"
_WS_COMPAT_PATHS = [
    "/ws/android/{id}",
    "/ws/android",
]
_WS_PATHS = [_WS_CANONICAL_PATH, *_WS_COMPAT_PATHS]
_WEBRTC_GW_PATH = "/ws/webrtc/{id}"


def _http_to_ws(url: str) -> str:
    """Convert ``http(s)://`` URL to ``ws(s)://``."""
    return url.replace("https://", "wss://").replace("http://", "ws://")


def _get_rest_base() -> str:
    """Return the gateway's HTTP base URL (no trailing slash)."""
    try:
        from core.port_config import get_service_port
        default = f"http://localhost:{get_service_port('state_machine')}"
    except Exception:
        default = _DEFAULT_GATEWAY_URL
    return os.getenv("GATEWAY_URL", default).rstrip("/")


def _build_stun_servers() -> List[str]:
    """
    Return STUN server URL list.

    Sources from ``GALAXY_STUN_URLS`` (comma-separated).  Falls back to the
    well-known Google STUN server so clients always have at least one entry.
    """
    raw = os.getenv("GALAXY_STUN_URLS", "").strip()
    if raw:
        urls = [u.strip() for u in raw.split(",") if u.strip()]
        if urls:
            return urls
    return [_DEFAULT_STUN]


def _build_turn_servers() -> List[Dict[str, Any]]:
    """
    Return TURN server list.

    Each entry follows the ``RTCIceServer`` dictionary shape::

        {"urls": "turn:...", "username": "...", "credential": "..."}

    Returns an **empty list** when ``GALAXY_TURN_URLS`` is not set — callers
    must handle this gracefully.
    """
    raw = os.getenv("GALAXY_TURN_URLS", "").strip()
    if not raw:
        return []

    turn_urls = [u.strip() for u in raw.split(",") if u.strip()]
    if not turn_urls:
        return []

    entry: Dict[str, Any] = {"urls": turn_urls[0] if len(turn_urls) == 1 else turn_urls}
    username = os.getenv("GALAXY_TURN_USERNAME", "").strip()
    credential = os.getenv("GALAXY_TURN_CREDENTIAL", "").strip()
    if username:
        entry["username"] = username
    if credential:
        entry["credential"] = credential
    return [entry]


def _build_transport_priority() -> List[str]:
    """
    Return ordered transport priority list.

    Sources from ``GALAXY_TRANSPORT_PRIORITY`` (comma-separated).
    Default: ``["tailscale", "intranet", "internet"]``.
    """
    raw = os.getenv("GALAXY_TRANSPORT_PRIORITY", "").strip()
    if raw:
        items = [t.strip() for t in raw.split(",") if t.strip()]
        if items:
            return items
    return list(_DEFAULT_TRANSPORT_PRIORITY)


def _build_feature_flags() -> Dict[str, bool]:
    """
    Return feature-flag dict sourced from environment variables.

    Flags
    -----
    tailscale_enabled
        True when ``GALAXY_TAILSCALE_ENABLED`` is ``1 / true / yes``.
    use_gateway_for_webrtc
        True unless ``GALAXY_USE_GATEWAY_FOR_WEBRTC`` is ``0 / false / no``.
    """
    tailscale_raw = os.getenv("GALAXY_TAILSCALE_ENABLED", "").strip().lower()
    tailscale_enabled = tailscale_raw in ("1", "true", "yes")

    gw_webrtc_raw = os.getenv("GALAXY_USE_GATEWAY_FOR_WEBRTC", "true").strip().lower()
    use_gw_webrtc = gw_webrtc_raw not in ("0", "false", "no")

    return {
        "tailscale_enabled": tailscale_enabled,
        "use_gateway_for_webrtc": use_gw_webrtc,
    }


def build_client_config() -> Dict[str, Any]:
    """
    Assemble the full client configuration dictionary.

    This function is intentionally free of FastAPI dependencies so it can be
    unit-tested without an ASGI environment.
    """
    rest_base = _get_rest_base()
    ws_base = _http_to_ws(rest_base)
    ws_url = f"{ws_base}{_WS_CANONICAL_PATH}"

    return {
        "ws_base": ws_base,
        "rest_base": rest_base,
        "ws_url": ws_url,
        "gateway_ws_url": ws_url,
        "ws_url_template": ws_url,
        "ws_canonical_path": _WS_CANONICAL_PATH,
        "ws_paths": list(_WS_PATHS),
        "ws_paths_compat": list(_WS_COMPAT_PATHS),
        "webrtc_gateway_ws_path": _WEBRTC_GW_PATH,
        "stun_servers": _build_stun_servers(),
        "turn_servers": _build_turn_servers(),
        "transport_priority": _build_transport_priority(),
        "feature_flags": _build_feature_flags(),
    }


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get("/api/v1/config")
async def client_config() -> Dict[str, Any]:
    """
    Return unified client configuration for Android and other clients.

    Android clients should call this endpoint at startup to obtain current
    connection settings, transport preferences, and ICE server lists rather
    than relying on hard-coded local configuration.

    **Placeholder substitution**: path values such as ``/ws/device/{id}``
    contain the literal token ``{id}``; replace it with the actual device
    identifier before connecting.

    **TURN servers**: ``turn_servers`` may be an empty list when the server
    is not configured with TURN credentials.  Clients must not crash in this
    case; native STUN / host candidates will still be attempted.

    **Transport priority**: clients should probe transports in the order
    given by ``transport_priority`` (e.g. Tailscale first, then local
    intranet, then public internet) and use the first reachable one.
    """
    try:
        return build_client_config()
    except Exception as exc:  # pragma: no cover
        logger.exception("Failed to build client config: %s", exc)
        raise
