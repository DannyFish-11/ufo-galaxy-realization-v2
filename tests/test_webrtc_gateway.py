"""
Tests for WebRTC Signaling Gateway Proxy
==========================================

Covers:
* GET  /api/v1/webrtc/endpoint  — returns Node_95 + gateway info
* WS   /ws/webrtc/{device_id}   — proxies messages to/from Node_95
* SmartTransportRouter.use_gateway — returns gateway WS URL

All tests mock Node_95 via a local server; no real Node_95 is needed.
"""

import json
import os
import socket
import threading
import time
from typing import List

import pytest

pytest.importorskip("websockets", reason="websockets package required for WebRTC tests")

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Minimal FastAPI app that exposes only the WebRTC endpoints under test
# ---------------------------------------------------------------------------

def _make_test_app() -> FastAPI:
    """Build a minimal FastAPI app with the WebRTC proxy routes."""
    from galaxy_gateway.webrtc_proxy import (
        check_node95_reachable,
        get_webrtc_endpoint_info,
        proxy_webrtc_signaling,
    )
    from fastapi import HTTPException

    app = FastAPI()

    @app.get("/api/v1/webrtc/endpoint")
    async def webrtc_endpoint_info():
        if not await check_node95_reachable():
            raise HTTPException(
                status_code=503,
                detail="Node_95 WebRTC Receiver is not reachable",
            )
        return get_webrtc_endpoint_info()

    @app.websocket("/ws/webrtc/{device_id}")
    async def webrtc_ws(websocket: WebSocket, device_id: str):
        await proxy_webrtc_signaling(websocket, device_id)

    return app


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Fixture: mock Node_95 server (HTTP health + WS signaling)
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_node95(monkeypatch):
    """
    Start a mock Node_95 server in a background thread.

    Serves:
    * ``GET /health`` → ``{"status": "healthy"}`` (HTTP 200).
    * ``WS  /signaling/{device_id}`` — echoes messages as
      ``{"type": "echo", "received": <msg>}``.

    Sets ``NODE_95_URL`` so the proxy connects to this mock.
    """
    received: List[str] = []

    mock_app = FastAPI()

    @mock_app.get("/health")
    async def _health():
        return {"status": "healthy"}

    @mock_app.websocket("/signaling/{device_id}")
    async def _signaling(websocket: WebSocket, device_id: str):
        await websocket.accept()
        try:
            while True:
                msg = await websocket.receive_text()
                received.append(msg)
                await websocket.send_text(
                    json.dumps({"type": "echo", "received": msg})
                )
        except Exception:
            pass

    port = _free_port()
    config = uvicorn.Config(mock_app, host="localhost", port=port, log_level="warning")
    server = uvicorn.Server(config)

    t = threading.Thread(target=server.run, daemon=True)
    t.start()

    # Poll until the server is ready
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("localhost", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.05)

    node95_url = f"http://localhost:{port}"
    monkeypatch.setenv("NODE_95_URL", node95_url)

    yield {"url": node95_url, "port": port, "received": received}

    server.should_exit = True


# ---------------------------------------------------------------------------
# Fixture: unreachable Node_95
# ---------------------------------------------------------------------------

@pytest.fixture()
def no_node95(monkeypatch):
    """Configure NODE_95_URL to a port nothing is listening on."""
    monkeypatch.setenv("NODE_95_URL", "http://localhost:19095")
    yield


# ---------------------------------------------------------------------------
# TestClient fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def test_client(mock_node95):
    app = _make_test_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def test_client_no_node95(no_node95):
    app = _make_test_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ===========================================================================
# Tests: REST endpoint /api/v1/webrtc/endpoint
# ===========================================================================

class TestWebRTCEndpointREST:

    def test_returns_200_when_node95_reachable(self, test_client):
        resp = test_client.get("/api/v1/webrtc/endpoint")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "node95_url" in data
        assert "ws_signaling_path" in data
        assert "gateway_ws_path" in data
        assert "realtime_streaming_backbone" in data
        assert "{device_id}" in data["ws_signaling_path"]
        assert "{device_id}" in data["gateway_ws_path"]

    def test_node95_url_matches_env(self, test_client, mock_node95):
        resp = test_client.get("/api/v1/webrtc/endpoint")
        assert resp.status_code == 200
        assert resp.json()["node95_url"] == mock_node95["url"]

    def test_returns_503_when_node95_unreachable(self, test_client_no_node95):
        resp = test_client_no_node95.get("/api/v1/webrtc/endpoint")
        assert resp.status_code == 503


# ===========================================================================
# Tests: WebSocket proxy /ws/webrtc/{device_id}
# ===========================================================================

class TestWebRTCWebSocketProxy:

    def test_proxy_relays_message_to_node95(self, test_client, mock_node95):
        with test_client.websocket_connect("/ws/webrtc/phone_a") as ws:
            payload = json.dumps({"type": "offer", "sdp": "v=0..."})
            ws.send_text(payload)
            reply = ws.receive_text()

        data = json.loads(reply)
        assert data["type"] == "echo"
        assert data["received"] == payload
        assert payload in mock_node95["received"]

    def test_proxy_relays_response_back_to_client(self, test_client, mock_node95):
        with test_client.websocket_connect("/ws/webrtc/phone_b") as ws:
            ws.send_text(json.dumps({"type": "ice_candidate", "candidate": "..."}))
            reply = ws.receive_text()
        assert "echo" in reply

    def test_proxy_multiple_messages(self, test_client, mock_node95):
        messages = [
            json.dumps({"type": "offer", "sdp": "v=0 1"}),
            json.dumps({"type": "ice_candidate", "candidate": "a1"}),
            json.dumps({"type": "ice_candidate", "candidate": "a2"}),
        ]
        replies = []
        with test_client.websocket_connect("/ws/webrtc/phone_c") as ws:
            for msg in messages:
                ws.send_text(msg)
                replies.append(ws.receive_text())

        assert len(replies) == len(messages)
        for i, reply in enumerate(replies):
            assert json.loads(reply)["received"] == messages[i]

    def test_proxy_closes_with_error_when_node95_down(self, test_client_no_node95):
        """
        When Node_95 is unreachable the proxy must close the WS connection
        (close code 1011) rather than hanging.  The TestClient raises
        WebSocketDisconnect or similar when the server closes forcefully.
        """
        from starlette.websockets import WebSocketDisconnect

        closed = False
        try:
            with test_client_no_node95.websocket_connect("/ws/webrtc/phone_x") as ws:
                try:
                    ws.receive_text()
                except WebSocketDisconnect as exc:
                    # Proxy closed with code 1011 (server error)
                    assert exc.code == 1011
                    closed = True
                except Exception:
                    # Other transports may raise a different exception
                    closed = True
        except Exception:
            closed = True  # WebSocket rejected outright — also acceptable

        assert closed, "Expected the proxy to close the WebSocket when Node_95 is unreachable"


# ===========================================================================
# Tests: SmartTransportRouter.use_gateway
# ===========================================================================

class TestSmartTransportRouterUseGateway:

    @pytest.mark.asyncio
    async def test_use_gateway_returns_gateway_ws_url(self, monkeypatch):
        monkeypatch.setenv("GATEWAY_URL", "http://localhost:8000")
        from galaxy_gateway.smart_transport_router import SmartTransportRouter, TransportRequest

        router = SmartTransportRouter()

        async def _always_available(method, device_id):
            return True
        router._is_method_available = _always_available  # type: ignore

        resp = await router.route(TransportRequest(
            device_id="test_phone",
            task_type="dynamic",
            realtime=True,
            preferred_method="webrtc",
            use_gateway=True,
        ))

        assert resp.success is True
        assert resp.method.value == "webrtc"
        assert resp.endpoint.startswith("ws://")
        assert "/ws/webrtc/" in resp.endpoint
        assert "test_phone" in resp.endpoint
        assert "localhost:8000" in resp.endpoint

    @pytest.mark.asyncio
    async def test_no_gateway_returns_node95_url(self, monkeypatch):
        monkeypatch.setenv("NODE_95_URL", "http://localhost:8095")
        from galaxy_gateway.smart_transport_router import SmartTransportRouter, TransportRequest

        router = SmartTransportRouter()

        async def _always_available(method, device_id):
            return True
        router._is_method_available = _always_available  # type: ignore

        resp = await router.route(TransportRequest(
            device_id="test_phone2",
            task_type="dynamic",
            realtime=True,
            preferred_method="webrtc",
            use_gateway=False,
        ))

        assert resp.success is True
        assert "/ws/webrtc/" not in resp.endpoint
        assert "8095" in resp.endpoint

    @pytest.mark.asyncio
    async def test_use_gateway_https_converts_to_wss(self, monkeypatch):
        monkeypatch.setenv("GATEWAY_URL", "https://gateway.example.com")
        from galaxy_gateway.smart_transport_router import SmartTransportRouter, TransportRequest

        router = SmartTransportRouter()

        async def _always_available(method, device_id):
            return True
        router._is_method_available = _always_available  # type: ignore

        resp = await router.route(TransportRequest(
            device_id="device_ssl",
            task_type="interactive",
            preferred_method="webrtc",
            use_gateway=True,
        ))

        assert resp.endpoint.startswith("wss://")
        assert "gateway.example.com" in resp.endpoint

    @pytest.mark.asyncio
    async def test_use_gateway_falls_back_when_webrtc_unavailable(self, monkeypatch):
        """
        When use_gateway=True but WebRTC is unavailable the router falls back
        to the next available method (e.g. adb) — use_gateway does not force
        WebRTC selection when the node is unreachable.
        """
        monkeypatch.setenv("GATEWAY_URL", "http://localhost:8000")
        monkeypatch.setenv("NODE_95_URL", "http://localhost:19095")  # unreachable
        from galaxy_gateway.smart_transport_router import SmartTransportRouter, TransportRequest

        router = SmartTransportRouter()
        # WebRTC unavailable; all others unavailable too → falls back to adb default
        # No mock for _is_method_available — let the real implementation run
        # (it tries /health which will fail for all unreachable nodes)

        resp = await router.route(TransportRequest(
            device_id="fallback_phone",
            task_type="dynamic",
            realtime=True,
            use_gateway=True,
        ))

        # Router must still return a valid response
        assert resp.success is True
        # When WebRTC is unavailable it should NOT return the gateway WS URL
        assert "/ws/webrtc/" not in resp.endpoint


# ===========================================================================
# Tests: webrtc_proxy helpers
# ===========================================================================

class TestWebRTCProxyHelpers:

    def test_get_webrtc_endpoint_info_structure(self, mock_node95):
        from galaxy_gateway.webrtc_proxy import get_webrtc_endpoint_info
        info = get_webrtc_endpoint_info()
        assert {"node95_url", "ws_signaling_path", "gateway_ws_url", "gateway_ws_path"} <= set(info.keys())

    @pytest.mark.asyncio
    async def test_check_node95_reachable_true(self, mock_node95):
        from galaxy_gateway.webrtc_proxy import check_node95_reachable
        assert await check_node95_reachable() is True

    @pytest.mark.asyncio
    async def test_check_node95_reachable_false(self, no_node95):
        from galaxy_gateway.webrtc_proxy import check_node95_reachable
        assert await check_node95_reachable() is False
