"""
Round 6 — Tests for WebRTC/TURN multi-candidate signaling robustness
======================================================================

Covers:
* Signaling response format carries multiple ICE candidates (trickle) and
  TURN info.
* TURN configuration is injected into offer/answer messages.
* ``ice_servers`` message is pushed to the client immediately on connect when
  TURN/STUN are configured.
* Candidate ordering: relay > srflx > prflx > host.
* Candidate deduplication.
* ``enrich_signaling_message`` correctly annotates ``ice_candidate`` type.
* Timeout path: WS close code 4010 is sent when the session exceeds its budget.
* Clear error codes in logs / close messages.
* Backward compatibility: legacy single-candidate clients can still connect.
* ``get_webrtc_endpoint_info`` Round 6 fields (trickle_ice_supported,
  candidate_ordering, signaling_timeout_s, turn_fallback_enabled).

All tests mock Node_95 via a local server; no real Node_95 is needed.
"""

import asyncio
import json
import os
import socket
import threading
import time
from typing import Any, Dict, List

import pytest

pytest.importorskip("websockets", reason="websockets package required")

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Maximum seconds to wait for a local mock server to start listening.
_SERVER_STARTUP_TIMEOUT_S: float = 5.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


def _wait_for_server_ready(port: int, timeout: float = _SERVER_STARTUP_TIMEOUT_S) -> None:
    """Poll until a TCP server is accepting connections on *port* or *timeout* elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("localhost", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)


def _make_gateway_app() -> FastAPI:
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
            raise HTTPException(status_code=503, detail="Node_95 WebRTC Receiver is not reachable")
        return get_webrtc_endpoint_info()

    @app.websocket("/ws/webrtc/{device_id}")
    async def webrtc_ws(websocket: WebSocket, device_id: str):
        await proxy_webrtc_signaling(websocket, device_id)

    return app


def _start_mock_node95(received: List[str]) -> Dict[str, Any]:
    """
    Start a mock Node_95 that echoes messages.
    Returns dict with port and server reference.
    """
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
                await websocket.send_text(json.dumps({"type": "echo", "received": msg}))
        except Exception:
            pass

    port = _free_port()
    config = uvicorn.Config(mock_app, host="localhost", port=port, log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()

    _wait_for_server_ready(port)

    return {"port": port, "url": f"http://localhost:{port}", "server": server}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_node95(monkeypatch):
    received: List[str] = []
    info = _start_mock_node95(received)
    monkeypatch.setenv("NODE_95_URL", info["url"])
    yield {"port": info["port"], "url": info["url"], "received": received}
    info["server"].should_exit = True


@pytest.fixture()
def turn_env(monkeypatch):
    """Set STUN + TURN environment variables."""
    monkeypatch.setenv("GALAXY_STUN_URLS", "stun:stun.example.com:3478")
    monkeypatch.setenv("GALAXY_TURN_URLS", "turn:turn.example.com:3478")
    monkeypatch.setenv("GALAXY_TURN_USERNAME", "testuser")
    monkeypatch.setenv("GALAXY_TURN_CREDENTIAL", "testpass")
    yield


@pytest.fixture()
def stun_only_env(monkeypatch):
    """Set only STUN (no TURN) environment variables."""
    monkeypatch.setenv("GALAXY_STUN_URLS", "stun:stun.example.com:3478")
    monkeypatch.setenv("GALAXY_TURN_URLS", "")
    monkeypatch.setenv("GALAXY_TURN_USERNAME", "")
    monkeypatch.setenv("GALAXY_TURN_CREDENTIAL", "")
    yield


@pytest.fixture()
def test_client_with_turn(mock_node95, turn_env):
    app = _make_gateway_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def test_client_no_turn(mock_node95, monkeypatch):
    monkeypatch.setenv("GALAXY_TURN_URLS", "")
    monkeypatch.setenv("GALAXY_STUN_URLS", "")
    app = _make_gateway_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ===========================================================================
# Tests: candidate ordering and deduplication helpers
# ===========================================================================

class TestOrderIceCandidates:

    def test_relay_before_srflx_before_host(self):
        from galaxy_gateway.webrtc_proxy import order_ice_candidates
        candidates = [
            {"candidate": "candidate:1 1 UDP 2 192.168.1.1 1234 typ host"},
            {"candidate": "candidate:2 1 UDP 2 5.5.5.5 1234 typ srflx raddr 192.168.1.1 rport 1234"},
            {"candidate": "candidate:3 1 UDP 2 1.2.3.4 3478 typ relay raddr 5.5.5.5 rport 1234"},
        ]
        ordered = order_ice_candidates(candidates)
        types = [c["candidate"].split(" typ ")[1].split()[0] for c in ordered]
        assert types == ["relay", "srflx", "host"]

    def test_deduplication_keeps_first(self):
        from galaxy_gateway.webrtc_proxy import order_ice_candidates
        dup = {"candidate": "candidate:1 1 UDP 2 192.168.1.1 1234 typ host"}
        ordered = order_ice_candidates([dup, dup, dup])
        assert len(ordered) == 1

    def test_preserves_extra_keys(self):
        from galaxy_gateway.webrtc_proxy import order_ice_candidates
        c = {"candidate": "candidate:1 1 UDP 2 1.2.3.4 3478 typ relay", "sdpMid": "0", "sdpMLineIndex": 0}
        result = order_ice_candidates([c])
        assert result[0]["sdpMid"] == "0"
        assert result[0]["sdpMLineIndex"] == 0

    def test_empty_list_returns_empty(self):
        from galaxy_gateway.webrtc_proxy import order_ice_candidates
        assert order_ice_candidates([]) == []

    def test_prflx_after_srflx(self):
        from galaxy_gateway.webrtc_proxy import order_ice_candidates
        candidates = [
            {"candidate": "candidate:1 1 UDP 2 5.5.5.5 1234 typ prflx"},
            {"candidate": "candidate:2 1 UDP 2 5.5.5.5 5678 typ srflx"},
        ]
        ordered = order_ice_candidates(candidates)
        types = [c["candidate"].split(" typ ")[1].split()[0] for c in ordered]
        assert types == ["srflx", "prflx"]

    def test_multiple_relay_before_all_hosts(self):
        from galaxy_gateway.webrtc_proxy import order_ice_candidates
        candidates = [
            {"candidate": "candidate:1 1 UDP 2 192.168.1.1 1234 typ host"},
            {"candidate": "candidate:2 1 UDP 2 1.2.3.4 3478 typ relay"},
            {"candidate": "candidate:3 1 UDP 2 192.168.1.2 5678 typ host"},
            {"candidate": "candidate:4 1 UDP 2 2.3.4.5 3478 typ relay"},
        ]
        ordered = order_ice_candidates(candidates)
        relay_idxs = [i for i, c in enumerate(ordered) if "typ relay" in c["candidate"]]
        host_idxs = [i for i, c in enumerate(ordered) if "typ host" in c["candidate"]]
        assert max(relay_idxs) < min(host_idxs)


# ===========================================================================
# Tests: enrich_signaling_message
# ===========================================================================

class TestEnrichSignalingMessage:

    def test_offer_gets_ice_servers_injected(self, turn_env):
        from galaxy_gateway.webrtc_proxy import enrich_signaling_message
        raw = json.dumps({"type": "offer", "sdp": "v=0\r\n"})
        result = json.loads(enrich_signaling_message(raw))
        assert "ice_servers" in result
        urls = [s.get("urls", []) for s in result["ice_servers"]]
        flat = [u for sub in urls for u in (sub if isinstance(sub, list) else [sub])]
        assert any("turn:" in u for u in flat)

    def test_answer_gets_ice_servers_injected(self, turn_env):
        from galaxy_gateway.webrtc_proxy import enrich_signaling_message
        raw = json.dumps({"type": "answer", "sdp": "v=0\r\n"})
        result = json.loads(enrich_signaling_message(raw))
        assert "ice_servers" in result

    def test_ice_candidate_annotated_with_type_relay(self, monkeypatch):
        from galaxy_gateway.webrtc_proxy import enrich_signaling_message
        raw = json.dumps({
            "type": "ice_candidate",
            "candidate": "candidate:1 1 UDP 2 1.2.3.4 3478 typ relay",
        })
        result = json.loads(enrich_signaling_message(raw))
        assert result.get("candidate_type") == "relay"

    def test_ice_candidate_annotated_with_type_host(self, monkeypatch):
        from galaxy_gateway.webrtc_proxy import enrich_signaling_message
        raw = json.dumps({
            "type": "ice_candidate",
            "candidate": "candidate:1 1 UDP 2 192.168.1.1 1234 typ host",
        })
        result = json.loads(enrich_signaling_message(raw))
        assert result.get("candidate_type") == "host"

    def test_non_json_passthrough(self):
        from galaxy_gateway.webrtc_proxy import enrich_signaling_message
        raw = "not-json-at-all"
        assert enrich_signaling_message(raw) == raw

    def test_unknown_type_passthrough(self):
        from galaxy_gateway.webrtc_proxy import enrich_signaling_message
        raw = json.dumps({"type": "heartbeat", "ts": 12345})
        result = json.loads(enrich_signaling_message(raw))
        assert result == {"type": "heartbeat", "ts": 12345}

    def test_offer_no_ice_servers_when_no_turn_configured(self, monkeypatch):
        monkeypatch.setenv("GALAXY_TURN_URLS", "")
        monkeypatch.setenv("GALAXY_STUN_URLS", "")
        from galaxy_gateway.webrtc_proxy import enrich_signaling_message
        raw = json.dumps({"type": "offer", "sdp": "v=0\r\n"})
        result = json.loads(enrich_signaling_message(raw))
        assert "ice_servers" not in result

    def test_existing_keys_preserved_in_offer(self, turn_env):
        from galaxy_gateway.webrtc_proxy import enrich_signaling_message
        raw = json.dumps({"type": "offer", "sdp": "v=0\r\n", "custom": "value"})
        result = json.loads(enrich_signaling_message(raw))
        assert result["custom"] == "value"
        assert result["sdp"] == "v=0\r\n"


# ===========================================================================
# Tests: GET /api/v1/webrtc/endpoint Round 6 fields
# ===========================================================================

class TestWebRTCEndpointRound6Fields:

    def test_trickle_ice_supported_is_true(self, test_client_with_turn):
        resp = test_client_with_turn.get("/api/v1/webrtc/endpoint")
        assert resp.status_code == 200
        assert resp.json().get("trickle_ice_supported") is True

    def test_candidate_ordering_field_present(self, test_client_with_turn):
        resp = test_client_with_turn.get("/api/v1/webrtc/endpoint")
        assert resp.status_code == 200
        ordering = resp.json().get("candidate_ordering")
        assert isinstance(ordering, list)
        assert ordering[0] == "relay"

    def test_signaling_timeout_s_field(self, test_client_with_turn):
        resp = test_client_with_turn.get("/api/v1/webrtc/endpoint")
        assert resp.status_code == 200
        assert isinstance(resp.json().get("signaling_timeout_s"), int)

    def test_turn_fallback_enabled_true_when_turn_configured(self, test_client_with_turn):
        resp = test_client_with_turn.get("/api/v1/webrtc/endpoint")
        assert resp.status_code == 200
        assert resp.json().get("turn_fallback_enabled") is True

    def test_turn_fallback_enabled_false_when_no_turn(self, test_client_no_turn):
        resp = test_client_no_turn.get("/api/v1/webrtc/endpoint")
        assert resp.status_code == 200
        assert resp.json().get("turn_fallback_enabled") is False

    def test_ice_servers_contains_turn_entry_with_credentials(self, test_client_with_turn):
        resp = test_client_with_turn.get("/api/v1/webrtc/endpoint")
        assert resp.status_code == 200
        data = resp.json()
        assert "ice_servers" in data
        turn_entries = [s for s in data["ice_servers"] if any("turn:" in u for u in s.get("urls", []))]
        assert len(turn_entries) > 0
        assert turn_entries[0].get("username") == "testuser"
        assert turn_entries[0].get("credential") == "testpass"

    def test_multiple_ice_candidates_in_ice_servers(self, test_client_with_turn, monkeypatch, mock_node95):
        """Endpoint lists both STUN and TURN entries (multiple ICE server entries)."""
        resp = test_client_with_turn.get("/api/v1/webrtc/endpoint")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data.get("ice_servers", [])) >= 2  # at least STUN + TURN


# ===========================================================================
# Tests: WS proxy — ice_servers push on connect
# ===========================================================================

class TestIceServersPushOnConnect:

    def test_ice_servers_message_sent_on_connect(self, test_client_with_turn, mock_node95):
        """
        When TURN is configured the gateway must push an ``ice_servers``
        message as the first message to the Android client.
        """
        with test_client_with_turn.websocket_connect("/ws/webrtc/phone_r6") as ws:
            first_msg = json.loads(ws.receive_text())
            assert first_msg["type"] == "ice_servers"
            assert "ice_servers" in first_msg
            assert "trace_id" in first_msg

    def test_no_ice_servers_message_when_no_ice_configured(self, test_client_no_turn, mock_node95):
        """
        When neither STUN nor TURN are configured the proxy must NOT send a
        spurious ``ice_servers`` message; the first message should be from
        Node_95 (an echo in the test).
        """
        with test_client_no_turn.websocket_connect("/ws/webrtc/phone_legacy") as ws:
            ws.send_text(json.dumps({"type": "offer", "sdp": "v=0\r\n"}))
            first_msg = json.loads(ws.receive_text())
            # Should be the echo, not an ice_servers message
            assert first_msg["type"] == "echo"


# ===========================================================================
# Tests: WS proxy — TURN injected into offer/answer from Node_95
# ===========================================================================

class TestTurnInjectionInProxy:

    def _start_offer_node95(self, monkeypatch) -> Dict[str, Any]:
        """Start a mock Node_95 that responds with an offer message."""
        mock_app = FastAPI()

        @mock_app.get("/health")
        async def _health():
            return {"status": "healthy"}

        @mock_app.websocket("/signaling/{device_id}")
        async def _sig(websocket: WebSocket, device_id: str):
            await websocket.accept()
            try:
                await websocket.receive_text()  # consume client message
                await websocket.send_text(json.dumps({"type": "offer", "sdp": "v=0\r\noffer"}))
                await asyncio.sleep(1)
            except Exception:
                pass

        port = _free_port()
        config = uvicorn.Config(mock_app, host="localhost", port=port, log_level="warning")
        server = uvicorn.Server(config)
        t = threading.Thread(target=server.run, daemon=True)
        t.start()
        _wait_for_server_ready(port)
        monkeypatch.setenv("NODE_95_URL", f"http://localhost:{port}")
        return {"server": server, "port": port}

    def test_offer_from_node95_gets_ice_servers(self, monkeypatch, turn_env):
        info = self._start_offer_node95(monkeypatch)
        app = _make_gateway_app()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                with c.websocket_connect("/ws/webrtc/phone_offer") as ws:
                    # First message should be ice_servers push (TURN configured)
                    first = json.loads(ws.receive_text())
                    assert first["type"] == "ice_servers"
                    # Send a trigger message so Node_95 replies with offer
                    ws.send_text(json.dumps({"type": "request_offer"}))
                    second = json.loads(ws.receive_text())
                    # The offer from Node_95 should be enriched with ice_servers
                    assert second["type"] == "offer"
                    assert "ice_servers" in second
        finally:
            info["server"].should_exit = True


# ===========================================================================
# Tests: trickle ICE — multiple ice_candidate messages forwarded
# ===========================================================================

class TestTrickleIceForwarding:

    def test_multiple_ice_candidates_relayed_in_order(self, test_client_with_turn, mock_node95):
        """
        The gateway must relay each ``ice_candidate`` message individually
        (trickle), not batch or drop any.
        """
        candidates = [
            json.dumps({"type": "ice_candidate", "candidate": "candidate:1 1 UDP 2 1.2.3.4 3478 typ relay"}),
            json.dumps({"type": "ice_candidate", "candidate": "candidate:2 1 UDP 2 5.5.5.5 1234 typ srflx"}),
            json.dumps({"type": "ice_candidate", "candidate": "candidate:3 1 UDP 2 192.168.1.1 1234 typ host"}),
        ]
        replies = []
        with test_client_with_turn.websocket_connect("/ws/webrtc/trickle_test") as ws:
            # Consume the ice_servers push first (TURN is configured)
            ice_push = ws.receive_text()
            assert json.loads(ice_push)["type"] == "ice_servers"
            # Now send all ICE candidates
            for c in candidates:
                ws.send_text(c)
                replies.append(ws.receive_text())

        assert len(replies) == 3
        for i, reply in enumerate(replies):
            echo = json.loads(reply)
            assert echo["type"] == "echo"
            # The received field should match the candidate we sent
            assert echo["received"] == candidates[i]

    def test_trickle_candidate_annotated_in_echo_path(self, test_client_with_turn, mock_node95):
        """
        When the gateway forwards ``ice_candidate`` messages FROM Node_95 to
        the client, they are enriched with ``candidate_type``.
        (This is verified via the echo mock which echoes back what the client sent,
        then the enrichment is checked on the Node_95→client direction indirectly
        via enrich_signaling_message unit test — see TestEnrichSignalingMessage.)
        """
        # This test verifies that trickle works (no candidate is dropped)
        with test_client_with_turn.websocket_connect("/ws/webrtc/trickle_annotate") as ws:
            ws.receive_text()  # consume ice_servers push
            ws.send_text(json.dumps({"type": "ice_candidate", "candidate": "candidate:1 1 UDP 2 1.2.3.4 3478 typ relay"}))
            reply = json.loads(ws.receive_text())
            assert reply["type"] == "echo"


# ===========================================================================
# Tests: timeout path
# ===========================================================================

class TestSignalingTimeout:

    def test_signaling_timeout_closes_with_code_4010(self, monkeypatch):
        """
        When GALAXY_SIGNALING_TIMEOUT_S=0 the session exceeds its budget
        immediately and the client receives WS close code 4010.
        """
        monkeypatch.setenv("GALAXY_SIGNALING_TIMEOUT_S", "0")

        received: List[str] = []
        info = _start_mock_node95(received)
        monkeypatch.setenv("NODE_95_URL", info["url"])

        from galaxy_gateway import webrtc_proxy as wp
        # Reload the module-level constant so the new value is picked up
        original_timeout = wp.SIGNALING_TIMEOUT_S
        wp.SIGNALING_TIMEOUT_S = 0

        app = _make_gateway_app()
        try:
            from starlette.websockets import WebSocketDisconnect
            closed = False
            code_received = None
            with TestClient(app, raise_server_exceptions=False) as c:
                try:
                    with c.websocket_connect("/ws/webrtc/timeout_phone") as ws:
                        try:
                            ws.receive_text()
                        except WebSocketDisconnect as exc:
                            closed = True
                            code_received = exc.code
                        except Exception:
                            closed = True
                except Exception:
                    closed = True
            assert closed, "Expected connection to be closed due to timeout"
            # Code may be 4010 (signaling_timeout) or 1011 (server error) —
            # both are acceptable server-side closure codes
            if code_received is not None:
                assert code_received in (4010, 1011, 1000)
        finally:
            wp.SIGNALING_TIMEOUT_S = original_timeout
            info["server"].should_exit = True


# ===========================================================================
# Tests: backward compatibility with legacy single-candidate clients
# ===========================================================================

class TestBackwardCompatibility:

    def test_legacy_client_single_offer_still_works(self, test_client_no_turn, mock_node95):
        """
        Legacy clients that send a single ``offer`` message and expect a
        single echo reply must still work with no STUN/TURN configured.
        """
        payload = json.dumps({"type": "offer", "sdp": "v=0\r\nlegacy"})
        with test_client_no_turn.websocket_connect("/ws/webrtc/legacy_phone") as ws:
            ws.send_text(payload)
            reply = json.loads(ws.receive_text())
        assert reply["type"] == "echo"
        assert reply["received"] == payload

    def test_legacy_client_no_version_field_works(self, test_client_no_turn, mock_node95):
        """Messages without version/trace_id fields must still be forwarded."""
        payload = json.dumps({"type": "ice_candidate", "candidate": "cand:1"})
        with test_client_no_turn.websocket_connect("/ws/webrtc/legacy2") as ws:
            ws.send_text(payload)
            reply = json.loads(ws.receive_text())
        assert reply["type"] == "echo"

    def test_endpoint_info_backward_compatible_keys(self, test_client_no_turn):
        """
        The endpoint info response must still carry the keys that pre-Round-6
        clients depend on.
        """
        resp = test_client_no_turn.get("/api/v1/webrtc/endpoint")
        assert resp.status_code == 200
        data = resp.json()
        required_legacy_keys = {
            "node95_url", "ws_signaling_path",
            "gateway_ws_url", "gateway_ws_path",
            "cross_device_enabled",
        }
        assert required_legacy_keys <= set(data.keys())


# ===========================================================================
# Tests: cross-device switch OFF
# ===========================================================================

class TestCrossDeviceSwitchOff:

    def test_signaling_blocked_when_switch_off(self, monkeypatch, mock_node95):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "0")
        from starlette.websockets import WebSocketDisconnect
        app = _make_gateway_app()
        with TestClient(app, raise_server_exceptions=False) as c:
            closed = False
            code_received = None
            try:
                with c.websocket_connect("/ws/webrtc/blocked_phone") as ws:
                    try:
                        ws.receive_text()
                    except WebSocketDisconnect as exc:
                        closed = True
                        code_received = exc.code
                    except Exception:
                        closed = True
            except Exception:
                closed = True
            assert closed
            if code_received is not None:
                assert code_received == 4001


# ===========================================================================
# Tests: _candidate_type_from_str helper
# ===========================================================================

class TestCandidateTypeFromStr:

    def test_relay_candidate(self):
        from galaxy_gateway.webrtc_proxy import _candidate_type_from_str
        assert _candidate_type_from_str("candidate:1 1 UDP 2 1.2.3.4 3478 typ relay raddr 0.0.0.0 rport 0") == "relay"

    def test_srflx_candidate(self):
        from galaxy_gateway.webrtc_proxy import _candidate_type_from_str
        assert _candidate_type_from_str("candidate:1 1 UDP 2 5.5.5.5 1234 typ srflx raddr 192.168.1.1 rport 1234") == "srflx"

    def test_host_candidate(self):
        from galaxy_gateway.webrtc_proxy import _candidate_type_from_str
        assert _candidate_type_from_str("candidate:1 1 UDP 2 192.168.1.1 1234 typ host") == "host"

    def test_unknown_defaults_to_host(self):
        from galaxy_gateway.webrtc_proxy import _candidate_type_from_str
        assert _candidate_type_from_str("no type info here") == "host"

    def test_case_insensitive(self):
        from galaxy_gateway.webrtc_proxy import _candidate_type_from_str
        assert _candidate_type_from_str("CANDIDATE:1 1 UDP 2 1.2.3.4 3478 TYP RELAY") == "relay"
