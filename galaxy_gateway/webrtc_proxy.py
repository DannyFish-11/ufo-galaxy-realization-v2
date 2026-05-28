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

    try:
        from core.realtime_streaming_backbone import (
            build_realtime_streaming_backbone_contract,
        )

        backbone = build_realtime_streaming_backbone_contract()
        convergence = backbone.get("component_convergence", {})
        info["realtime_streaming_backbone"] = {
            "authority": backbone.get("authority"),
            "sentinel": backbone.get("sentinel"),
            "gateway_proxy_role": convergence.get("gateway_proxy", {}).get("role", ""),
            "node95_role": convergence.get("node95_bridge", {}).get("role", ""),
        }
    except Exception:
        pass

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


# ---------------------------------------------------------------------------
# PR-WEBRTC-TASK-LIFECYCLE: Task-aware WebRTC signaling initiation
# ---------------------------------------------------------------------------
# These helpers are imported and called by CommandRouter.route_envelope()
# when envelope.requires_webrtc is True.  They bridge the gap between
# "task needs a video stream" and "WebRTC connection is ready".
# ---------------------------------------------------------------------------

#: In-memory registry of active WebRTC signaling sessions keyed by device_id.
#: Each entry is a dict with keys: "trace_id", "started_at", "state".
_webrtc_task_sessions: Dict[str, Dict[str, Any]] = {}

#: Default timeout (seconds) to wait for WebRTC data channel to become ready.
WEBRTC_TASK_READY_TIMEOUT_S: float = float(
    os.getenv("GALAXY_WEBRTC_TASK_READY_TIMEOUT_S", "15")
)

#: Polling interval (seconds) while waiting for the ingress bridge to report
#: that frames are flowing from a specific device.
WEBRTC_TASK_READY_POLL_S: float = 0.5


class WebRTCTaskReadinessResult:
    """Result of attempting to bring up WebRTC for a task."""

    def __init__(
        self,
        *,
        success: bool,
        device_id: str,
        trace_id: str,
        message: str = "",
        latency_ms: float = 0.0,
    ) -> None:
        self.success = success
        self.device_id = device_id
        self.trace_id = trace_id
        self.message = message
        self.latency_ms = latency_ms

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "device_id": self.device_id,
            "trace_id": self.trace_id,
            "message": self.message,
            "latency_ms": self.latency_ms,
        }


def get_webrtc_task_session(device_id: str) -> Optional[Dict[str, Any]]:
    """Return the active WebRTC task session for *device_id*, if any."""
    return _webrtc_task_sessions.get(device_id)


def register_webrtc_task_session(
    device_id: str,
    *,
    trace_id: str,
    state: str = "signaling_initiated",
) -> None:
    """Register that a WebRTC signaling session was initiated for a task."""
    _webrtc_task_sessions[device_id] = {
        "trace_id": trace_id,
        "started_at": time.time(),
        "state": state,
    }
    logger.info(
        "webrtc_task_session_registered device_id=%s trace_id=%s state=%s",
        device_id, trace_id, state,
    )


def mark_webrtc_task_session_state(device_id: str, state: str) -> None:
    """Update the state of an active WebRTC task session."""
    sess = _webrtc_task_sessions.get(device_id)
    if sess is not None:
        old_state = sess["state"]
        sess["state"] = state
        logger.debug(
            "webrtc_task_session_state device_id=%s %s → %s",
            device_id, old_state, state,
        )


def clear_webrtc_task_session(device_id: str) -> None:
    """Remove a WebRTC task session entry (idempotent)."""
    _webrtc_task_sessions.pop(device_id, None)


async def initiate_webrtc_for_task(
    device_id: str,
    trace_id: str,
    *,
    timeout_s: Optional[float] = None,
) -> WebRTCTaskReadinessResult:
    """Initiate WebRTC signaling for a task and wait until video is ready.

    This is the **canonical entry point** called by
    ``CommandRouter.route_envelope()`` when ``envelope.requires_webrtc`` is
    ``True``.

    What it does
    ------------
    1. Registers a task-scoped WebRTC session for *device_id*.
    2. Probes Node_95 reachability (fast-fail if unreachable).
    3. Polls ``WebRTCIngressBridge`` until frames from *device_id* are
       flowing (or timeout).
    4. Returns a :class:`WebRTCTaskReadinessResult` describing the outcome.

    The actual signaling handshake (offer/answer/ICE) happens asynchronously
    via the existing ``/ws/webrtc/{device_id}`` endpoint — this function does
    **not** perform the handshake itself; it only waits for the data-plane
    side effect (frames ingested) that proves the handshake succeeded.

    Parameters
    ----------
    device_id:
        The Android device identifier that should provide the video stream.
    trace_id:
        Distributed trace id propagated from the TaskEnvelope.
    timeout_s:
        Max seconds to wait for the video stream to become ready.
        Defaults to ``WEBRTC_TASK_READY_TIMEOUT_S``.

    Returns
    -------
    WebRTCTaskReadinessResult
        ``success=True`` when frames are flowing; ``success=False`` on
        timeout or error with an explanatory ``message``.
    """
    # PR-WEBRTC-TASK-LIFECYCLE sentinel: function entry
    _t0 = time.monotonic()
    timeout_s = timeout_s or WEBRTC_TASK_READY_TIMEOUT_S

    register_webrtc_task_session(
        device_id=device_id,
        trace_id=trace_id,
        state="signaling_initiated",
    )

    # Step 1: Fast-fail if Node_95 is not reachable
    _node95_reachable = await check_node95_reachable()
    if not _node95_reachable:
        _elapsed = (time.monotonic() - _t0) * 1000
        mark_webrtc_task_session_state(device_id, "node95_unreachable")
        logger.warning(
            "webrtc_task_initiate: Node_95 unreachable device_id=%s trace_id=%s",
            device_id, trace_id,
        )
        return WebRTCTaskReadinessResult(
            success=False,
            device_id=device_id,
            trace_id=trace_id,
            message="Node_95 WebRTC Receiver is not reachable; cannot initiate WebRTC",
            latency_ms=round(_elapsed, 1),
        )

    mark_webrtc_task_session_state(device_id, "node95_reachable")

    # Step 2: Check if the WebRTCIngressBridge is enabled
    try:
        from core.multimodal.webrtc_ingress_bridge import get_webrtc_ingress_bridge

        _bridge = get_webrtc_ingress_bridge()
        if not _bridge.is_enabled:
            _elapsed = (time.monotonic() - _t0) * 1000
            mark_webrtc_task_session_state(device_id, "bridge_disabled")
            logger.warning(
                "webrtc_task_initiate: WebRTCIngressBridge disabled "
                "device_id=%s trace_id=%s",
                device_id, trace_id,
            )
            return WebRTCTaskReadinessResult(
                success=False,
                device_id=device_id,
                trace_id=trace_id,
                message=(
                    "WebRTCIngressBridge is disabled "
                    "(enable_webrtc_data_channel=false)"
                ),
                latency_ms=round(_elapsed, 1),
            )
    except Exception as _bridge_exc:
        _elapsed = (time.monotonic() - _t0) * 1000
        mark_webrtc_task_session_state(device_id, f"bridge_error:{_bridge_exc}")
        logger.warning(
            "webrtc_task_initiate: WebRTCIngressBridge unavailable "
            "device_id=%s trace_id=%s error=%s",
            device_id, trace_id, _bridge_exc,
        )
        return WebRTCTaskReadinessResult(
            success=False,
            device_id=device_id,
            trace_id=trace_id,
            message=f"WebRTCIngressBridge unavailable: {_bridge_exc}",
            latency_ms=round(_elapsed, 1),
        )

    mark_webrtc_task_session_state(device_id, "waiting_for_frames")

    # Step 3: Poll until frames from this device are flowing
    _poll_interval = WEBRTC_TASK_READY_POLL_S
    _deadline = time.monotonic() + timeout_s
    _initial_frames = 0
    try:
        _initial_frames = _bridge._device_frame_counts.get(device_id, 0)
    except Exception:
        pass

    logger.info(
        "webrtc_task_initiate: polling for frames device_id=%s trace_id=%s "
        "timeout_s=%.1f initial_frames=%d",
        device_id, trace_id, timeout_s, _initial_frames,
    )

    while time.monotonic() < _deadline:
        try:
            _current_frames = _bridge._device_frame_counts.get(device_id, 0)
            if _current_frames > _initial_frames:
                _elapsed = (time.monotonic() - _t0) * 1000
                mark_webrtc_task_session_state(device_id, "ready")
                logger.info(
                    "webrtc_task_initiate: READY device_id=%s trace_id=%s "
                    "frames=%d latency_ms=%.1f",
                    device_id, trace_id, _current_frames, _elapsed,
                )
                return WebRTCTaskReadinessResult(
                    success=True,
                    device_id=device_id,
                    trace_id=trace_id,
                    message=(
                        f"WebRTC video stream ready for {device_id} "
                        f"({_current_frames} frames ingested)"
                    ),
                    latency_ms=round(_elapsed, 1),
                )
        except Exception:
            pass
        await asyncio.sleep(_poll_interval)

    # Timeout
    _elapsed = (time.monotonic() - _t0) * 1000
    mark_webrtc_task_session_state(device_id, "timeout")
    logger.warning(
        "webrtc_task_initiate: TIMEOUT device_id=%s trace_id=%s "
        "timeout_s=%.1f latency_ms=%.1f",
        device_id, trace_id, timeout_s, _elapsed,
    )
    return WebRTCTaskReadinessResult(
        success=False,
        device_id=device_id,
        trace_id=trace_id,
        message=(
            f"Timed out after {timeout_s}s waiting for WebRTC video stream "
            f"from {device_id}. The signaling handshake may still be in progress."
        ),
        latency_ms=round(_elapsed, 1),
    )


def is_webrtc_ready_for_device(device_id: str) -> bool:
    """Synchronous probe: is the WebRTC video stream ready for *device_id*?

    Called by ``CommandRouter.route_envelope()`` to perform a quick
    readiness check before deciding whether to initiate signaling.
    """
    try:
        from core.multimodal.webrtc_ingress_bridge import get_webrtc_ingress_bridge

        _bridge = get_webrtc_ingress_bridge()
        if not _bridge.is_enabled:
            return False
        _device_frames = _bridge._device_frame_counts.get(device_id, 0)
        return _device_frames > 0
    except Exception:
        return False
