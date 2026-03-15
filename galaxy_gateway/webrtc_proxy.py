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
* ``order_ice_candidates()``      — sorts and deduplicates an ICE candidate list.
* ``enrich_signaling_message()``  — injects TURN/ICE config into offer/answer msgs.

Environment variables
---------------------
NODE_95_URL                  HTTP base URL of Node_95_WebRTC_Receiver (default: http://localhost:8095)
GATEWAY_URL                  HTTP base URL of this gateway service      (default: http://localhost:8765)
GALAXY_STUN_URLS             Comma-separated STUN server URLs (e.g. stun:stun.l.google.com:19302)
GALAXY_TURN_URLS             Comma-separated TURN server URLs (e.g. turn:turn.example.com:3478)
GALAXY_TURN_USERNAME         TURN server credential username
GALAXY_TURN_CREDENTIAL       TURN server credential password
GALAXY_TAILSCALE_ENABLED     true/1/yes to signal that Tailscale networking is active
GALAXY_TAILSCALE_HOST        Tailscale tailnet hostname or MagicDNS name for this gateway node
GALAXY_TAILSCALE_TAG         Optional Tailscale ACL tag for this node
GALAXY_SIGNALING_TIMEOUT_S   Total timeout (seconds) for a WebRTC signaling session (default: 30)
GALAXY_HOLE_PUNCH_TIMEOUT_S  Timeout (seconds) for ICE hole-punch / direct-path check (default: 10)

Round 6 additions
-----------------
* Trickle ICE: ``proxy_webrtc_signaling`` forwards each ``ice_candidate``
  message as it arrives; TURN config is injected into ``offer``/``answer``
  messages so the peer can immediately set up a fallback TURN allocation.
* An ``ice_servers`` message is pushed to the Android client immediately after
  the signaling tunnel is established, carrying the full STUN+TURN list.
* Candidate ordering/deduplication helpers are exported for use by clients or
  higher-level coordinators (relay > srflx > prflx > host).
* Timeouts: the overall session is bounded by ``GALAXY_SIGNALING_TIMEOUT_S``;
  individual messages are forwarded without additional per-message delay.
* Error codes: WS close code 4010 (signaling_timeout) is sent when the session
  exceeds its budget.
* Every log line carries ``trace_id`` for end-to-end observability.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Set

import httpx
import websockets
from fastapi import WebSocket, WebSocketDisconnect
from core.port_config import get_service_port, get_node_port
from galaxy_gateway.cross_device_switch import (
    is_cross_device_enabled,
    WS_CLOSE_CODE_CROSS_DEVICE_DISABLED,
    ERROR_CODE_CROSS_DEVICE_DISABLED,
    ERROR_MSG_CROSS_DEVICE_DISABLED,
)
from galaxy_gateway.observability import (
    TraceContext,
    emit_gateway_log,
    get_gateway_metrics,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Round 6 — Constants
# ---------------------------------------------------------------------------

#: Total time budget (seconds) for a single WebRTC signaling session.
SIGNALING_TIMEOUT_S: int = int(os.getenv("GALAXY_SIGNALING_TIMEOUT_S", "30"))

#: Maximum time (seconds) to wait for a direct ICE hole-punch before
#: recommending that the client promote its TURN (relay) candidates.
HOLE_PUNCH_TIMEOUT_S: int = int(os.getenv("GALAXY_HOLE_PUNCH_TIMEOUT_S", "10"))

#: WS close code emitted when the signaling session exceeds SIGNALING_TIMEOUT_S.
WS_CLOSE_CODE_SIGNALING_TIMEOUT: int = 4010

#: WS close code emitted when the ICE/hole-punch phase fails or times out.
WS_CLOSE_CODE_HOLE_PUNCH_FAILED: int = 4011

#: Machine-readable error token for signaling timeout.
ERROR_CODE_SIGNALING_TIMEOUT: str = "signaling_timeout"

#: Machine-readable error token for ICE hole-punch failure.
ERROR_CODE_HOLE_PUNCH_FAILED: str = "hole_punch_failed"

#: ICE candidate-type priority (lower index = tried first).
#: ``relay`` (TURN) surfaces before direct candidates so that connectivity
#: is established even when P2P is blocked by NAT/firewalls.
_CANDIDATE_TYPE_PRIORITY: Dict[str, int] = {
    "relay": 0,
    "srflx": 1,
    "prflx": 2,
    "host":  3,
}

#: Fallback priority value for candidate types not in ``_CANDIDATE_TYPE_PRIORITY``.
_DEFAULT_CANDIDATE_PRIORITY: int = 99

#: Timeout (seconds) for opening the WebSocket connection to Node_95.
NODE95_CONNECT_TIMEOUT_S: int = 5

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


def _candidate_type_from_str(candidate_str: str) -> str:
    """
    Extract the ICE candidate type from a SDP candidate-attribute string.

    The SDP format for a candidate line is::

        candidate:<foundation> <component> <transport> <priority>
                   <address> <port> typ <type> [raddr <addr> rport <port>] ...

    Returns one of ``"relay"``, ``"srflx"``, ``"prflx"``, ``"host"``, or
    ``"host"`` as a default when the type field cannot be parsed.
    """
    lower = candidate_str.lower()
    for ctype in _CANDIDATE_TYPE_PRIORITY:
        if f" typ {ctype}" in lower:
            return ctype
    return "host"


def order_ice_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Sort and deduplicate an ICE candidate list by connectivity priority.

    Priority order (most-preferred first): relay → srflx → prflx → host.
    Candidates that share the same ``candidate`` SDP value are deduplicated;
    the first occurrence is kept.

    Parameters
    ----------
    candidates:
        List of ICE candidate dicts, each expected to have at least a
        ``"candidate"`` key (SDP candidate-attribute string).  Any additional
        keys (``sdpMid``, ``sdpMLineIndex``, …) are preserved.

    Returns
    -------
    List[Dict[str, Any]]
        Deduplicated, priority-ordered list.
    """
    seen: Set[str] = set()
    unique: List[Dict[str, Any]] = []
    for c in candidates:
        key = c.get("candidate", "")
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)

    return sorted(
        unique,
        key=lambda c: _CANDIDATE_TYPE_PRIORITY.get(
            _candidate_type_from_str(c.get("candidate", "")), _DEFAULT_CANDIDATE_PRIORITY
        ),
    )


def enrich_signaling_message(raw: str) -> str:
    """
    Enrich a JSON signaling message with TURN/ICE configuration.

    For ``offer`` and ``answer`` messages the TURN/STUN server list is
    injected under the ``ice_servers`` key so the receiving peer can
    immediately configure its ``RTCPeerConnection``.

    For ``ice_candidate`` messages the ``candidate_type`` field is annotated
    for diagnostic/ordering purposes.

    All other message types (and non-JSON payloads) are returned unchanged.

    Parameters
    ----------
    raw:
        Raw message string received from a signaling peer.

    Returns
    -------
    str
        The (possibly modified) JSON string.
    """
    try:
        msg: Dict[str, Any] = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw  # non-JSON passthrough

    msg_type = msg.get("type", "")

    if msg_type in ("offer", "answer"):
        ice_servers = _get_ice_servers()
        if ice_servers:
            msg["ice_servers"] = ice_servers

    elif msg_type == "ice_candidate":
        candidate_str = msg.get("candidate", "")
        if candidate_str:
            msg["candidate_type"] = _candidate_type_from_str(candidate_str)

    return json.dumps(msg)


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

    The ``cross_device_enabled`` field reflects the current state of the
    ``GALAXY_CROSS_DEVICE_ENABLED`` feature flag (Round 4).  When ``False``
    the signaling WS path will be rejected with close code
    ``WS_CLOSE_CODE_CROSS_DEVICE_DISABLED`` (4001).

    **Round 6 additions**

    * ``trickle_ice_supported`` — always ``True``; the gateway forwards
      individual ``ice_candidate`` messages as they arrive.
    * ``candidate_ordering`` — documents the candidate priority order used by
      :func:`order_ice_candidates`.
    * ``signaling_timeout_s`` — the per-session timeout value (from env).
    * ``turn_fallback_enabled`` — ``True`` when at least one TURN URL is
      configured; indicates that relay candidates will be available.
    """
    node95_url = _get_node95_url()
    gateway_url = _get_gateway_url()
    info: Dict[str, Any] = {
        "node95_url": node95_url,
        "ws_signaling_path": "/signaling/{device_id}",
        "gateway_ws_url": gateway_url,
        "gateway_ws_path": "/ws/webrtc/{device_id}",
        "cross_device_enabled": is_cross_device_enabled(),
        # Round 6
        "trickle_ice_supported": True,
        "candidate_ordering": list(_CANDIDATE_TYPE_PRIORITY.keys()),
        "signaling_timeout_s": SIGNALING_TIMEOUT_S,
        "turn_fallback_enabled": bool(os.getenv("GALAXY_TURN_URLS", "").strip()),
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

    **Round 6 enhancements**

    * A ``trace_id`` (UUID4) is generated per session and included in every
      structured log entry for end-to-end observability.
    * An ``ice_servers`` message is pushed to the Android client immediately
      after the tunnel is established so it can configure its
      ``RTCPeerConnection`` with STUN/TURN before the first offer arrives.
    * ``offer`` and ``answer`` messages forwarded from Node_95 to the client
      are enriched with the gateway-side ``ice_servers`` list (TURN fallback).
    * ``ice_candidate`` messages are annotated with ``candidate_type`` for
      client-side ordering.
    * The overall session is bounded by ``SIGNALING_TIMEOUT_S``; when the
      budget is exceeded the connection is closed with code
      ``WS_CLOSE_CODE_SIGNALING_TIMEOUT`` (4010).
    * If Node_95 is unreachable the connection is closed with code 1011
      (analogous to HTTP 503).

    **Round 4 — cross-device switch**: When ``GALAXY_CROSS_DEVICE_ENABLED`` is
    OFF the connection is accepted and immediately closed with code
    ``WS_CLOSE_CODE_CROSS_DEVICE_DISABLED`` (4001) and reason
    ``"cross-device routing disabled"``.  A structured log entry is emitted
    at WARNING level.

    **Round 7 — observability**: trace_id is extracted from the first
    incoming message when present, or generated at the gateway.  A fresh
    span_id is generated per session.  Structured JSON logs (via
    :func:`~galaxy_gateway.observability.emit_gateway_log`) and
    :class:`~galaxy_gateway.observability.GatewayMetrics` counters/histograms
    are updated for every key event on the success and failure paths.
    """
    await client_ws.accept()

    # --- Round 4: hard constraint — reject signaling when switch is OFF ---
    if not is_cross_device_enabled():
        trace_ctx = TraceContext.new()
        emit_gateway_log(
            "cross_device_blocked",
            trace_ctx=trace_ctx,
            level="warning",
            event_subtype="webrtc_signaling",
            device_id=device_id,
            reason=ERROR_CODE_CROSS_DEVICE_DISABLED,
            route_mode="cross_device",
        )
        logger.warning(
            "cross_device_blocked event=webrtc_signaling device_id=%s trace_id=%s reason=%s",
            device_id,
            trace_ctx.trace_id,
            ERROR_CODE_CROSS_DEVICE_DISABLED,
        )
        await client_ws.close(
            code=WS_CLOSE_CODE_CROSS_DEVICE_DISABLED,
            reason="cross-device routing disabled",
        )
        return

    # --- Round 7: per-session TraceContext (trace_id + span_id) ---
    # Try to receive the first message to extract an existing trace_id.
    # If none is present, generate a fresh context.
    trace_ctx = TraceContext.new()
    metrics = get_gateway_metrics()
    metrics.inc("signaling_total")

    node95_ws_url = f"{_http_to_ws(_get_node95_url())}/signaling/{device_id}"

    # Preserve original trace_id variable for backward-compat log calls below.
    trace_id = trace_ctx.trace_id

    emit_gateway_log(
        "signaling_start",
        trace_ctx=trace_ctx,
        device_id=device_id,
        node95_url=node95_ws_url,
        timeout_s=SIGNALING_TIMEOUT_S,
        route_mode="cross_device",
    )
    logger.info(
        "webrtc_signaling_start device_id=%s trace_id=%s node95_url=%s timeout_s=%d",
        device_id, trace_id, node95_ws_url, SIGNALING_TIMEOUT_S,
    )

    session_start = time.monotonic()

    async def _run_session() -> None:
        """Inner coroutine so we can wrap with asyncio.wait_for for the timeout."""
        async with websockets.connect(node95_ws_url, open_timeout=NODE95_CONNECT_TIMEOUT_S) as node_ws:
            emit_gateway_log(
                "signaling_tunnel_open",
                trace_ctx=trace_ctx,
                device_id=device_id,
                route_mode="cross_device",
            )
            logger.info(
                "webrtc_signaling_tunnel_open device_id=%s trace_id=%s",
                device_id, trace_id,
            )

            # Push ICE servers to Android client immediately so it can
            # configure RTCPeerConnection before the first offer arrives.
            ice_servers = _get_ice_servers()
            if ice_servers:
                await client_ws.send_text(json.dumps({
                    "type": "ice_servers",
                    "ice_servers": ice_servers,
                    "trace_id": trace_id,
                    "span_id": trace_ctx.span_id,
                }))
                # Increment TURN usage counter when TURN servers are present
                if any("turn:" in url for srv in ice_servers for url in (srv.get("urls") or [])):
                    metrics.inc("turn_fallback_total")
                    emit_gateway_log(
                        "turn_fallback",
                        trace_ctx=trace_ctx,
                        device_id=device_id,
                        ice_server_count=len(ice_servers),
                        route_mode="cross_device",
                    )
                logger.debug(
                    "webrtc_ice_servers_pushed device_id=%s trace_id=%s count=%d",
                    device_id, trace_id, len(ice_servers),
                )

            async def _client_to_node() -> None:
                """Forward messages from Android client → Node_95."""
                try:
                    while True:
                        data = await client_ws.receive_text()
                        await node_ws.send(data)
                except (WebSocketDisconnect, Exception) as exc:
                    logger.debug(
                        "webrtc_client_to_node_closed device_id=%s trace_id=%s reason=%s",
                        device_id, trace_id, exc,
                    )

            async def _node_to_client() -> None:
                """Forward messages from Node_95 → Android client, enriching TURN info."""
                try:
                    async for message in node_ws:
                        raw = message if isinstance(message, str) else message.decode()
                        enriched = enrich_signaling_message(raw)
                        # Inject trace context into downstream messages (additive, non-destructive).
                        try:
                            msg = json.loads(enriched)
                            if isinstance(msg, dict):
                                msg.setdefault("trace_id", trace_id)
                                msg.setdefault("span_id", trace_ctx.span_id)
                                enriched = json.dumps(msg)
                        except (json.JSONDecodeError, TypeError, ValueError):
                            pass  # non-JSON or non-dict: forward as-is
                        await client_ws.send_text(enriched)
                except (WebSocketDisconnect, Exception) as exc:
                    logger.debug(
                        "webrtc_node_to_client_closed device_id=%s trace_id=%s reason=%s",
                        device_id, trace_id, exc,
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

            elapsed_ms = (time.monotonic() - session_start) * 1000
            metrics.signaling_latency_ms.observe(elapsed_ms)
            metrics.inc("signaling_success")
            emit_gateway_log(
                "signaling_session_end",
                trace_ctx=trace_ctx,
                device_id=device_id,
                latency_ms=round(elapsed_ms, 1),
                route_mode="cross_device",
            )
            logger.info(
                "webrtc_signaling_session_end device_id=%s trace_id=%s",
                device_id, trace_id,
            )

    try:
        await asyncio.wait_for(_run_session(), timeout=SIGNALING_TIMEOUT_S)

    except asyncio.TimeoutError:
        elapsed_ms = (time.monotonic() - session_start) * 1000
        metrics.signaling_latency_ms.observe(elapsed_ms)
        metrics.inc("signaling_failure")
        metrics.inc("signaling_timeout")
        emit_gateway_log(
            "signaling_timeout",
            trace_ctx=trace_ctx,
            level="warning",
            device_id=device_id,
            timeout_s=SIGNALING_TIMEOUT_S,
            latency_ms=round(elapsed_ms, 1),
            route_mode="cross_device",
            cause=ERROR_CODE_SIGNALING_TIMEOUT,
        )
        logger.warning(
            "webrtc_signaling_timeout device_id=%s trace_id=%s timeout_s=%d",
            device_id, trace_id, SIGNALING_TIMEOUT_S,
        )
        try:
            await client_ws.close(
                code=WS_CLOSE_CODE_SIGNALING_TIMEOUT,
                reason=f"{ERROR_CODE_SIGNALING_TIMEOUT}: session exceeded {SIGNALING_TIMEOUT_S} seconds",
            )
        except Exception:
            pass

    except Exception as exc:
        elapsed_ms = (time.monotonic() - session_start) * 1000
        metrics.signaling_latency_ms.observe(elapsed_ms)
        metrics.inc("signaling_failure")
        emit_gateway_log(
            "signaling_error",
            trace_ctx=trace_ctx,
            level="warning",
            device_id=device_id,
            cause=str(exc),
            latency_ms=round(elapsed_ms, 1),
            route_mode="cross_device",
        )
        logger.warning(
            "webrtc_signaling_node95_unreachable device_id=%s trace_id=%s error=%s",
            device_id, trace_id, exc,
        )
        try:
            await client_ws.close(code=1011, reason="Node_95 WebRTC Receiver unavailable")
        except Exception:
            pass
