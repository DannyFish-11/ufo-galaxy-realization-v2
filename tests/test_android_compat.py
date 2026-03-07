"""
tests/test_android_compat.py
============================

Tests for the Android cross-device compatibility layer:

1. HTTP device API shim  (core/routes/compat.py  +  core/api_routes.py)
   - POST /api/devices/register
   - GET  /api/devices/list
   - POST /api/devices/heartbeat
   - POST /api/devices/unregister

2. WebSocket legacy paths  (galaxy_gateway/app.py)
   - /ws/device/{device_id}
   - /ws/ufo3/{device_id}
   - /ws/android

3. Protocol compatibility parser  (galaxy_gateway/protocol/compat.py)
   - AIP/1.0 normalisation (register / heartbeat aliases)
   - AIP/2.0 normalisation
   - AIP/3.0 pass-through
"""

import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ============================================================================
# 1. HTTP Device API Compatibility Shim
# ============================================================================

@pytest.fixture(scope="module")
def compat_client():
    """TestClient backed by the full core API router (includes compat shim)."""
    from core.api_routes import create_api_routes
    app = FastAPI()
    router = create_api_routes()
    app.include_router(router)
    with TestClient(app) as c:
        yield c


class TestLegacyDeviceHttpAPI:
    """Tests for /api/devices/* backward-compatible endpoints."""

    def test_register_device(self, compat_client):
        """POST /api/devices/register should register a new device."""
        device_id = f"test-{uuid.uuid4().hex[:8]}"
        r = compat_client.post(
            "/api/devices/register",
            json={
                "device_id": device_id,
                "device_type": "android_phone",
                "device_name": "TestDevice",
                "capabilities": ["screen", "touch"],
                "os_version": "Android 13",
                "app_version": "1.0.0",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["device_id"] == device_id

    def test_register_device_minimal(self, compat_client):
        """POST /api/devices/register with only device_id should succeed."""
        device_id = f"min-{uuid.uuid4().hex[:8]}"
        r = compat_client.post(
            "/api/devices/register",
            json={"device_id": device_id},
        )
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_list_devices(self, compat_client):
        """GET /api/devices/list should return device list."""
        # Register a device first so there is at least one entry
        device_id = f"list-{uuid.uuid4().hex[:8]}"
        compat_client.post("/api/devices/register", json={"device_id": device_id})

        r = compat_client.get("/api/devices/list")
        assert r.status_code == 200
        data = r.json()
        assert "devices" in data
        assert "total" in data
        assert isinstance(data["devices"], list)
        ids = [d["device_id"] for d in data["devices"]]
        assert device_id in ids

    def test_heartbeat_known_device(self, compat_client):
        """POST /api/devices/heartbeat for a registered device should succeed."""
        device_id = f"hb-{uuid.uuid4().hex[:8]}"
        compat_client.post("/api/devices/register", json={"device_id": device_id})

        r = compat_client.post(
            "/api/devices/heartbeat",
            json={"device_id": device_id, "status": {"battery": 80}},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["device_id"] == device_id

    def test_heartbeat_unknown_device(self, compat_client):
        """POST /api/devices/heartbeat for an unknown device should still return 200."""
        r = compat_client.post(
            "/api/devices/heartbeat",
            json={"device_id": "nonexistent-device-xyz"},
        )
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_unregister_device(self, compat_client):
        """POST /api/devices/unregister should mark device as offline."""
        device_id = f"unreg-{uuid.uuid4().hex[:8]}"
        compat_client.post("/api/devices/register", json={"device_id": device_id})

        r = compat_client.post(
            "/api/devices/unregister",
            json={"device_id": device_id},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["device_id"] == device_id

    def test_unregister_unknown_device(self, compat_client):
        """POST /api/devices/unregister for an unknown device should be a no-op."""
        r = compat_client.post(
            "/api/devices/unregister",
            json={"device_id": "totally-unknown-device"},
        )
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_legacy_and_v1_coexist(self, compat_client):
        """Both legacy and v1 register endpoints should work independently."""
        legacy_id = f"leg-{uuid.uuid4().hex[:8]}"
        v1_id = f"v1-{uuid.uuid4().hex[:8]}"

        r_legacy = compat_client.post(
            "/api/devices/register", json={"device_id": legacy_id}
        )
        r_v1 = compat_client.post(
            "/api/v1/devices/register", json={"device_id": v1_id}
        )

        assert r_legacy.status_code == 200
        assert r_v1.status_code == 200

        # Both should appear in v1 list
        r_list = compat_client.get("/api/v1/devices")
        listed_ids = [d["device_id"] for d in r_list.json()["devices"]]
        assert legacy_id in listed_ids
        assert v1_id in listed_ids


# ============================================================================
# 2. WebSocket legacy paths  (galaxy_gateway/app.py)
# ============================================================================

@pytest.fixture(scope="module")
def gw_client():
    """
    TestClient backed by the galaxy_gateway FastAPI app.

    The lifespan context initialises background tasks (heartbeat checker etc.)
    which require a running event loop.  Using TestClient as a context manager
    starts/stops the lifespan automatically.
    """
    from galaxy_gateway.app import app as gateway_app
    with TestClient(gateway_app) as c:
        yield c


class TestLegacyWebSocketPaths:
    """Smoke-test that the legacy WS paths accept connections."""

    def _connect_and_ping(self, client: TestClient, path: str) -> None:
        """Open a WS connection, send a heartbeat, check for ack."""
        device_id = f"ws-{uuid.uuid4().hex[:8]}"
        url = path.format(device_id=device_id)
        with client.websocket_connect(url) as ws:
            ws.send_text(json.dumps({
                "version": "3.0",
                "type": "heartbeat",
                "device_id": device_id,
            }))
            msg = ws.receive_json()
            assert msg.get("type") == "heartbeat_ack"

    def test_ws_device_path(self, gw_client):
        """/ws/device/{device_id} accepts connections and handles heartbeats."""
        self._connect_and_ping(gw_client, "/ws/device/{device_id}")

    def test_ws_ufo3_path(self, gw_client):
        """/ws/ufo3/{device_id} accepts connections and handles heartbeats."""
        self._connect_and_ping(gw_client, "/ws/ufo3/{device_id}")

    def test_ws_android_with_device_id(self, gw_client):
        """/ws/android?device_id=... accepts connections."""
        device_id = f"android-{uuid.uuid4().hex[:8]}"
        with gw_client.websocket_connect(f"/ws/android?device_id={device_id}") as ws:
            ws.send_text(json.dumps({
                "version": "3.0",
                "type": "heartbeat",
                "device_id": device_id,
            }))
            msg = ws.receive_json()
            assert msg.get("type") == "heartbeat_ack"

    def test_ws_android_auto_device_id(self, gw_client):
        """/ws/android without device_id auto-assigns one."""
        # If no device_id is provided we still expect a heartbeat_ack
        with gw_client.websocket_connect("/ws/android") as ws:
            ws.send_text(json.dumps({
                "version": "3.0",
                "type": "heartbeat",
                "device_id": "ignored-by-server",
            }))
            msg = ws.receive_json()
            assert msg.get("type") == "heartbeat_ack"


# ============================================================================
# 3. Protocol compatibility parser
# ============================================================================

class TestProtocolCompat:
    """Unit-tests for galaxy_gateway.protocol.compat.parse_message_compat."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from galaxy_gateway.protocol.compat import parse_message_compat
        from galaxy_gateway.protocol.aip_v3 import MessageType
        self.parse = parse_message_compat
        self.MessageType = MessageType

    # --- AIP/1.0 ---

    def test_v1_register_alias(self):
        """AIP/1.0 'register' maps to MessageType.DEVICE_REGISTER."""
        msg = self.parse(json.dumps({
            "type": "register",
            "device_id": "dev-001",
        }))
        assert msg.type == self.MessageType.DEVICE_REGISTER
        assert msg.device_id == "dev-001"

    def test_v1_agent_register_alias(self):
        """AIP/1.0 'agent_register' maps to MessageType.DEVICE_REGISTER."""
        msg = self.parse({"type": "agent_register", "device_id": "dev-002"})
        assert msg.type == self.MessageType.DEVICE_REGISTER

    def test_v1_device_register_alias(self):
        """AIP/1.0 'device_register' maps to MessageType.DEVICE_REGISTER."""
        msg = self.parse({"type": "device_register", "device_id": "dev-003"})
        assert msg.type == self.MessageType.DEVICE_REGISTER

    def test_v1_heartbeat_alias(self):
        """AIP/1.0 'heartbeat' maps to MessageType.DEVICE_HEARTBEAT."""
        msg = self.parse({"type": "heartbeat", "device_id": "dev-004"})
        assert msg.type == self.MessageType.DEVICE_HEARTBEAT

    def test_v1_agent_heartbeat_alias(self):
        """AIP/1.0 'agent_heartbeat' maps to MessageType.DEVICE_HEARTBEAT."""
        msg = self.parse({"type": "agent_heartbeat", "device_id": "dev-005"})
        assert msg.type == self.MessageType.DEVICE_HEARTBEAT

    def test_v1_device_heartbeat_alias(self):
        """AIP/1.0 'device_heartbeat' maps to MessageType.DEVICE_HEARTBEAT."""
        msg = self.parse({"type": "device_heartbeat", "device_id": "dev-006"})
        assert msg.type == self.MessageType.DEVICE_HEARTBEAT

    def test_v1_missing_device_id_defaults(self):
        """AIP/1.0 message without device_id gets 'unknown' as default."""
        msg = self.parse({"type": "heartbeat"})
        assert msg.device_id == "unknown"

    # --- AIP/2.0 ---

    def test_v2_accepted(self):
        """AIP/2.0 message is normalised and accepted."""
        msg = self.parse({
            "version": "2.0",
            "type": "heartbeat",
            "device_id": "dev-v2",
        })
        assert msg.type == self.MessageType.DEVICE_HEARTBEAT
        assert msg.device_id == "dev-v2"

    def test_v2_register(self):
        """AIP/2.0 device_register is accepted."""
        msg = self.parse({
            "version": "2.0",
            "type": "device_register",
            "device_id": "dev-v2-reg",
        })
        assert msg.type == self.MessageType.DEVICE_REGISTER

    # --- AIP/3.0 ---

    def test_v3_passthrough(self):
        """AIP/3.0 message passes through unchanged."""
        msg = self.parse({
            "version": "3.0",
            "type": "heartbeat",
            "device_id": "dev-v3",
        })
        assert msg.type == self.MessageType.DEVICE_HEARTBEAT
        assert msg.version == "3.0"

    def test_v3_device_register(self):
        """AIP/3.0 device_register passes through unchanged."""
        msg = self.parse({
            "version": "3.0",
            "type": "device_register",
            "device_id": "dev-v3-reg",
        })
        assert msg.type == self.MessageType.DEVICE_REGISTER

    def test_json_string_input(self):
        """parse_message_compat accepts a raw JSON string."""
        payload = json.dumps({"type": "heartbeat", "device_id": "str-test"})
        msg = self.parse(payload)
        assert msg.type == self.MessageType.DEVICE_HEARTBEAT


# ============================================================================
# Entry point
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
