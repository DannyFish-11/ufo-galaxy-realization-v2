"""
tests/test_aip_v3_ws_contracts.py
Snapshot / contract tests for AIP v3 message flows on Android WS entrypoints.

PR-G1 "协议契约与回归守护"

Scope
-----
1. **Message-shape contracts** — every AIP v3 message (inbound and outbound)
   must carry the canonical required fields:
   ``version``, ``type``, ``device_id``, ``message_id``, ``timestamp``.

2. **Flow snapshots** — the response shape for each canonical Android→Server
   message type is compared against a stored inline snapshot so that any
   breaking structural change is caught immediately:
   * ``device_register`` → ``device_register_ack``
   * ``heartbeat`` → ``heartbeat_ack``
   * ``capability_report`` → ``capability_report_ack``
   * ``task_result`` → (no response; bridge handles asynchronously)
   * ``error`` → (no response; bridge handles by logging)
   * ``task_end`` → ``task_end_ack``

3. **Android WS endpoint contracts** — the three Android WS entrypoints
   exposed by the gateway:
   * ``/ws/android/{device_id}``
   * ``/ws/android`` (with and without ``?device_id=`` query param)
   * ``/ws/device/{device_id}``
   all accept AIP v3 connections and honour the protocol contract.

4. **Regression guard** — after receiving a ``device_register`` + a
   ``heartbeat``, the WS endpoint must *not* silently drop the response
   or change its ``type`` field; the field set is locked to the snapshot.

All tests are *unit / integration* level — no external services or running
servers are needed.  WS tests use ``fastapi.testclient.TestClient``.
"""

import json
import time
import uuid
from typing import Any, Dict, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mk_v3(msg_type: str, device_id: str = "test-device-001", **extra) -> Dict[str, Any]:
    """Return a fully-compliant AIP v3.0 message dict."""
    return {
        "version": "3.0",
        "type": msg_type,
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        **extra,
    }


def _mk_ws() -> MagicMock:
    """Minimal mock WebSocket for bridge unit tests."""
    ws = MagicMock()
    ws.send = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------

# Each snapshot is an ordered dict of (key → expected_type_or_value).
# A value of ``...`` (Ellipsis) means "field must be present, any value".
# A value of a Python type means "field must be present and of that type".
# A plain non-type value means "field must equal that value exactly".

_T_STR = str
_T_INT = int
_T_BOOL = bool

SNAPSHOT_REGISTER_ACK: Dict[str, Any] = {
    "version": "3.0",
    "type": "device_register_ack",
    "message_id": _T_STR,
    "device_id": _T_STR,
    "timestamp": _T_INT,
    "success": _T_BOOL,
}

SNAPSHOT_HEARTBEAT_ACK: Dict[str, Any] = {
    "version": "3.0",
    "type": "heartbeat_ack",
    "message_id": _T_STR,
    "device_id": _T_STR,
    "timestamp": _T_INT,
}

SNAPSHOT_CAPABILITY_REPORT_ACK: Dict[str, Any] = {
    "version": "3.0",
    "type": "capability_report_ack",
    "message_id": _T_STR,
    "device_id": _T_STR,
    "timestamp": _T_INT,
}

SNAPSHOT_TASK_END_ACK: Dict[str, Any] = {
    "version": "3.0",
    "type": "task_end_ack",
    "message_id": _T_STR,
    "device_id": _T_STR,
    "timestamp": _T_INT,
    "task_id": ...,         # present, any value (may be None)
    "status": "acknowledged",
}

SNAPSHOT_DEVICE_STATUS_ACK: Dict[str, Any] = {
    "version": "3.0",
    "type": "device_status_ack",
    "message_id": _T_STR,
    "device_id": _T_STR,
    "timestamp": _T_INT,
    "status": "received",
}


def _check_snapshot(response: Dict[str, Any], snapshot: Dict[str, Any], *, label: str) -> None:
    """Assert that *response* matches all entries in *snapshot*."""
    for key, expected in snapshot.items():
        assert key in response, (
            f"[{label}] snapshot field '{key}' is missing from response {list(response.keys())}"
        )
        value = response[key]
        if expected is ...:
            pass  # any value is fine
        elif isinstance(expected, type):
            assert isinstance(value, expected), (
                f"[{label}] field '{key}': expected type {expected.__name__!r}, "
                f"got {type(value).__name__!r} = {value!r}"
            )
        else:
            assert value == expected, (
                f"[{label}] field '{key}': expected {expected!r}, got {value!r}"
            )


# ===========================================================================
# 1. Message-shape contracts (unit tests — no I/O)
# ===========================================================================

class TestAIPv3MessageShapeContract:
    """Verify that every constructed AIP v3 message carries the canonical fields."""

    REQUIRED_FIELDS = ("version", "type", "device_id", "message_id", "timestamp")

    def _assert_required(self, msg: Dict[str, Any], label: str) -> None:
        for field in self.REQUIRED_FIELDS:
            assert field in msg, (
                f"[{label}] required AIP v3 field '{field}' is missing. "
                f"Present keys: {list(msg.keys())}"
            )

    # --- AIPMessage Pydantic model ---

    def test_register_message_shape(self):
        from galaxy_gateway.protocol.aip_v3 import (
            AIPMessage, AIPDeviceType, MessageType,
        )
        msg = AIPMessage(
            type=MessageType.DEVICE_REGISTER,
            device_id="shape-test-001",
            device_type=AIPDeviceType.ANDROID_PHONE,
        )
        d = json.loads(msg.model_dump_json())
        self._assert_required(d, "device_register AIPMessage")
        assert d["version"] == "3.0"
        assert d["type"] == "device_register"

    def test_heartbeat_message_shape(self):
        from galaxy_gateway.protocol.aip_v3 import AIPMessage, MessageType
        msg = AIPMessage(
            type=MessageType.DEVICE_HEARTBEAT,
            device_id="shape-test-hb",
        )
        d = json.loads(msg.model_dump_json())
        self._assert_required(d, "heartbeat AIPMessage")
        assert d["type"] == "heartbeat"

    def test_task_submit_message_shape(self):
        from galaxy_gateway.protocol.aip_v3 import AIPMessage, MessageType
        msg = AIPMessage(
            type=MessageType.TASK_SUBMIT,
            device_id="shape-test-task",
            task_id=str(uuid.uuid4()),
        )
        d = json.loads(msg.model_dump_json())
        self._assert_required(d, "task_submit AIPMessage")
        assert d["type"] == "task_submit"

    def test_error_message_shape(self):
        from galaxy_gateway.protocol.aip_v3 import AIPMessage, MessageType
        msg = AIPMessage(
            type=MessageType.ERROR,
            device_id="shape-test-err",
            error="Something went wrong",
        )
        d = json.loads(msg.model_dump_json())
        self._assert_required(d, "error AIPMessage")
        assert d["type"] == "error"

    # --- MessageBuilder (server-side outbound) ---

    def test_builder_register_ack_shape(self):
        from galaxy_gateway.android_bridge import MessageBuilder
        ack = MessageBuilder.device_register_ack("builder-001", success=True)
        self._assert_required(ack, "MessageBuilder.device_register_ack")
        assert ack["type"] == "device_register_ack"
        assert ack["success"] is True

    def test_builder_heartbeat_ack_shape(self):
        from galaxy_gateway.android_bridge import MessageBuilder
        ack = MessageBuilder.heartbeat_ack("builder-002")
        self._assert_required(ack, "MessageBuilder.heartbeat_ack")
        assert ack["type"] == "heartbeat_ack"

    def test_builder_task_assign_shape(self):
        from galaxy_gateway.android_bridge import MessageBuilder
        task_id = str(uuid.uuid4())
        msg = MessageBuilder.task_assign(
            device_id="builder-003",
            task_id=task_id,
            task_type="gui_task",
            payload={"action": "click", "x": 100, "y": 200},
        )
        self._assert_required(msg, "MessageBuilder.task_assign")
        assert msg["type"] == "task_assign"
        assert msg["task_id"] == task_id

    def test_builder_error_shape(self):
        from galaxy_gateway.android_bridge import MessageBuilder
        msg = MessageBuilder.error(
            device_id="builder-004",
            error_code="E001",
            error_message="Dispatch failed",
        )
        self._assert_required(msg, "MessageBuilder.error")
        assert msg["type"] == "error"

    def test_builder_capability_report_ack_shape(self):
        from galaxy_gateway.android_bridge import MessageBuilder
        ack = MessageBuilder.capability_report_ack("builder-005")
        self._assert_required(ack, "MessageBuilder.capability_report_ack")
        assert ack["type"] == "capability_report_ack"


# ===========================================================================
# 2. Flow snapshots — AndroidBridge handlers (unit tests)
# ===========================================================================

@pytest.fixture()
def bridge():
    """Fresh AndroidBridge instance for each test."""
    from galaxy_gateway.android_bridge import AndroidBridge
    return AndroidBridge()


class TestFlowSnapshots:
    """
    Snapshot tests for the canonical AIP v3 message flows.

    Each test:
    1. Constructs an inbound AIP v3 message dict.
    2. Passes it through AndroidBridge.handle_message().
    3. Checks the response against the stored inline snapshot.
    """

    # ------------------------------------------------------------------
    # device_register → device_register_ack
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_device_register_ack_snapshot(self, bridge):
        ws = _mk_ws()
        msg = _mk_v3(
            "device_register",
            device_id="snap-reg-001",
            platform="android",
            model="Pixel 8 Pro",
        )
        response = await bridge.handle_message(ws, msg)
        assert response is not None, "device_register must produce a response"
        _check_snapshot(response, SNAPSHOT_REGISTER_ACK, label="device_register_ack")
        assert response["device_id"] == "snap-reg-001"

    @pytest.mark.asyncio
    async def test_device_register_missing_device_id_returns_error(self, bridge):
        """A register message without device_id returns an error (not device_register_ack).

        The bridge validates mandatory fields (type, device_id) before dispatching
        to the handler.  Missing device_id causes an immediate error response so
        that the client always gets explicit feedback.
        """
        ws = _mk_ws()
        # Send a register message without device_id — bridge should reject with error.
        msg = {
            "version": "3.0",
            "type": "device_register",
            "message_id": str(uuid.uuid4()),
            "timestamp": int(time.time() * 1000),
            # device_id intentionally omitted
        }
        response = await bridge.handle_message(ws, msg)
        assert response is not None
        # Bridge returns error for missing mandatory fields
        assert response["type"] == "error"
        assert "message_id" in response
        assert "device_id" in response

    # ------------------------------------------------------------------
    # heartbeat → heartbeat_ack
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_heartbeat_ack_snapshot_registered(self, bridge):
        """Heartbeat from a registered device returns a well-formed ack."""
        ws = _mk_ws()
        device_id = "snap-hb-001"
        # Register first
        await bridge.handle_message(ws, _mk_v3("device_register", device_id=device_id))

        hb = _mk_v3("heartbeat", device_id=device_id)
        response = await bridge.handle_message(ws, hb)
        assert response is not None, "heartbeat must produce a response"
        _check_snapshot(response, SNAPSHOT_HEARTBEAT_ACK, label="heartbeat_ack (registered)")
        assert response["device_id"] == device_id

    @pytest.mark.asyncio
    async def test_heartbeat_ack_snapshot_unregistered(self, bridge):
        """Heartbeat from an *unregistered* device still returns a well-formed ack."""
        ws = _mk_ws()
        hb = _mk_v3("heartbeat", device_id="snap-hb-unreg")
        response = await bridge.handle_message(ws, hb)
        assert response is not None, "heartbeat must produce a response even for unregistered devices"
        _check_snapshot(response, SNAPSHOT_HEARTBEAT_ACK, label="heartbeat_ack (unregistered)")

    # ------------------------------------------------------------------
    # capability_report → capability_report_ack
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_capability_report_ack_snapshot(self, bridge):
        ws = _mk_ws()
        device_id = "snap-cap-001"
        await bridge.handle_message(ws, _mk_v3("device_register", device_id=device_id))

        cap_msg = _mk_v3(
            "capability_report",
            device_id=device_id,
            payload={
                "supported_actions": ["tap", "swipe", "screenshot"],
                "device_type": "android_phone",
            },
        )
        response = await bridge.handle_message(ws, cap_msg)
        assert response is not None, "capability_report must produce a response"
        _check_snapshot(response, SNAPSHOT_CAPABILITY_REPORT_ACK, label="capability_report_ack")
        assert response["device_id"] == device_id

    # ------------------------------------------------------------------
    # task_result — no outbound response (fire-and-forget)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_task_result_no_response(self, bridge):
        """task_result is handled internally (Future / memory backflow) and returns None."""
        ws = _mk_ws()
        device_id = "snap-tr-001"
        await bridge.handle_message(ws, _mk_v3("device_register", device_id=device_id))

        task_msg = _mk_v3(
            "task_result",
            device_id=device_id,
            task_id=str(uuid.uuid4()),
            status="completed",
            payload={"result": "ok"},
        )
        response = await bridge.handle_message(ws, task_msg)
        # Bridge does not send a response for task_result — returns None.
        assert response is None, (
            "task_result should not generate an outbound response; "
            f"got {response!r}"
        )

    # ------------------------------------------------------------------
    # error — no outbound response (logged only)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_error_message_no_response(self, bridge):
        """Error messages from devices are logged but do not generate an ACK."""
        ws = _mk_ws()
        device_id = "snap-err-001"
        await bridge.handle_message(ws, _mk_v3("device_register", device_id=device_id))

        err_msg = _mk_v3(
            "error",
            device_id=device_id,
            error_code="E_EXEC_FAIL",
            error_message="Action execution failed",
        )
        response = await bridge.handle_message(ws, err_msg)
        assert response is None, (
            "error messages should not generate an outbound response; "
            f"got {response!r}"
        )

    # ------------------------------------------------------------------
    # task_end → task_end_ack
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_task_end_ack_snapshot(self, bridge):
        ws = _mk_ws()
        device_id = "snap-te-001"
        task_id = str(uuid.uuid4())
        await bridge.handle_message(ws, _mk_v3("device_register", device_id=device_id))

        te_msg = _mk_v3(
            "task_end",
            device_id=device_id,
            task_id=task_id,
            status="completed",
        )
        response = await bridge.handle_message(ws, te_msg)
        assert response is not None, "task_end must produce a response"
        _check_snapshot(response, SNAPSHOT_TASK_END_ACK, label="task_end_ack")
        assert response["device_id"] == device_id
        assert response["task_id"] == task_id

    # ------------------------------------------------------------------
    # device_status → device_status_ack
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_device_status_ack_snapshot(self, bridge):
        ws = _mk_ws()
        device_id = "snap-ds-001"
        await bridge.handle_message(ws, _mk_v3("device_register", device_id=device_id))

        status_msg = _mk_v3(
            "device_status",
            device_id=device_id,
            payload={"battery": 85, "cpu": 12, "memory_free_mb": 1024},
        )
        response = await bridge.handle_message(ws, status_msg)
        assert response is not None, "device_status must produce a response"
        _check_snapshot(response, SNAPSHOT_DEVICE_STATUS_ACK, label="device_status_ack")


# ===========================================================================
# 3. Protocol contracts — normalised message invariants
# ===========================================================================

class TestProtocolContracts:
    """
    Verify the compat layer always produces AIP v3 compliant dicts/objects.
    These act as regression guards on the compat normalisation pipeline.
    """

    REQUIRED_V3_FIELDS = ("version", "type", "device_id")

    # --- parse_message_compat output contract ---

    @pytest.mark.parametrize("raw", [
        # AIP/1.0 aliases
        {"type": "register",         "device_id": "c-01"},
        {"type": "heartbeat",        "device_id": "c-02"},
        {"type": "agent_register",   "device_id": "c-03"},
        {"type": "registration",     "device_id": "c-04"},
        {"type": "command_result",   "device_id": "c-05"},
        {"type": "status_update",    "device_id": "c-06"},
        {"type": "task_execute",     "device_id": "c-07"},
        # AIP/2.0
        {"version": "2.0", "type": "device_register",  "device_id": "c-08"},
        {"version": "2.0", "type": "heartbeat",         "device_id": "c-09"},
        # AIP/3.0 — pass-through
        {"version": "3.0", "type": "heartbeat",         "device_id": "c-10"},
        {"version": "3.0", "type": "device_register",   "device_id": "c-11"},
        {"version": "3.0", "type": "task_submit",       "device_id": "c-12"},
    ])
    def test_compat_output_always_v3(self, raw):
        from galaxy_gateway.protocol.compat import parse_message_compat
        from galaxy_gateway.protocol.aip_v3 import AIPMessage
        msg = parse_message_compat(dict(raw))
        assert isinstance(msg, AIPMessage), "parse_message_compat must return AIPMessage"
        assert msg.version.startswith("3"), (
            f"Expected version 3.x, got {msg.version!r}"
        )
        assert msg.device_id, "device_id must be non-empty after compat normalisation"

    # --- normalise_to_v3_dict output contract ---

    @pytest.mark.parametrize("raw", [
        {"type": "register",         "device_id": "n-01", "extra_field": "preserved"},
        {"version": "2.0", "type": "heartbeat", "device_id": "n-02", "platform": "android"},
        {"version": "3.0", "type": "capability_report", "device_id": "n-03"},
    ])
    def test_normalise_to_v3_dict_contract(self, raw):
        from galaxy_gateway.protocol.compat import normalise_to_v3_dict
        out = normalise_to_v3_dict(dict(raw))
        assert isinstance(out, dict)
        assert out.get("version") == "3.0"
        for field in self.REQUIRED_V3_FIELDS:
            assert field in out, (
                f"Required field '{field}' missing from normalise_to_v3_dict output"
            )

    def test_normalise_preserves_extra_fields(self):
        """normalise_to_v3_dict must NOT drop application-level extra fields."""
        from galaxy_gateway.protocol.compat import normalise_to_v3_dict
        raw = {
            "type": "register",
            "device_id": "n-extra",
            "platform": "android",
            "model": "Pixel 8",
            "os_version": "Android 14",
        }
        out = normalise_to_v3_dict(raw)
        assert out.get("platform") == "android", "extra field 'platform' must be preserved"
        assert out.get("model") == "Pixel 8", "extra field 'model' must be preserved"
        assert out.get("os_version") == "Android 14", "extra field 'os_version' must be preserved"

    def test_trace_id_injected_in_compat(self):
        """trace_id must always be injected by parse_message_compat."""
        from galaxy_gateway.protocol.compat import inject_trace_metadata
        out = inject_trace_metadata({"type": "heartbeat", "device_id": "n-trace"})
        assert "trace_id" in out, "trace_id must be injected"
        # Must be a valid UUID
        _uuid = uuid.UUID(out["trace_id"])
        assert str(_uuid) == out["trace_id"]

    def test_route_mode_injected_in_compat(self):
        """route_mode must always be injected when absent."""
        from galaxy_gateway.protocol.compat import inject_trace_metadata
        out = inject_trace_metadata({"type": "heartbeat", "device_id": "n-rm"})
        assert "route_mode" in out, "route_mode must be injected"
        assert out["route_mode"] == "cross_device"

    def test_existing_trace_id_preserved(self):
        """A pre-existing trace_id must NOT be overwritten."""
        from galaxy_gateway.protocol.compat import inject_trace_metadata
        original_tid = str(uuid.uuid4())
        out = inject_trace_metadata({
            "type": "heartbeat",
            "device_id": "n-notrace",
            "trace_id": original_tid,
        })
        assert out["trace_id"] == original_tid


# ===========================================================================
# 4. Android WS endpoint contracts — gateway TestClient
# ===========================================================================

@pytest.fixture(scope="module")
def gw_client():
    """
    TestClient backed by a minimal FastAPI app that exposes only the
    Android WS routes under test.

    A minimal app is used (rather than the full ``galaxy_gateway.app``) so
    that infrastructure dependencies (NATS, heartbeat scheduler, etc.) that
    are unrelated to the protocol contract do not block the test.  The WS
    handler (``_handle_android_ws``) is the same production function used
    by the real gateway.
    """
    from fastapi import FastAPI, Query, WebSocket
    from fastapi.testclient import TestClient
    from galaxy_gateway.app import _handle_android_ws

    minimal_app = FastAPI()

    @minimal_app.websocket("/ws/android/{device_id}")
    async def ws_android_primary(websocket: WebSocket, device_id: str):
        await _handle_android_ws(websocket, device_id)

    @minimal_app.websocket("/ws/android")
    async def ws_android_fallback(
        websocket: WebSocket, device_id: str = Query(None)
    ):
        if not device_id:
            import uuid as _uuid
            device_id = str(_uuid.uuid4())
        await _handle_android_ws(websocket, device_id)

    @minimal_app.websocket("/ws/device/{device_id}")
    async def ws_device(websocket: WebSocket, device_id: str):
        await _handle_android_ws(websocket, device_id)

    with TestClient(minimal_app) as c:
        yield c


def _ws_register_and_heartbeat(
    client,
    path: str,
    device_id: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Helper: open WS, send device_register, receive ack, send heartbeat,
    receive ack.  Return (register_ack, heartbeat_ack).
    """
    with client.websocket_connect(path) as ws:
        # Step 1 – register
        ws.send_text(json.dumps(_mk_v3("device_register", device_id=device_id,
                                       platform="android", model="Test Phone")))
        reg_ack = ws.receive_json()

        # Step 2 – heartbeat
        ws.send_text(json.dumps(_mk_v3("heartbeat", device_id=device_id)))
        hb_ack = ws.receive_json()

    return reg_ack, hb_ack


class TestAndroidWSEndpointContracts:
    """
    Verify that every Android WS entrypoint honours the AIP v3 protocol
    contract for the register→heartbeat flow.
    """

    def _assert_register_ack_contract(self, ack: Dict[str, Any], path: str) -> None:
        _check_snapshot(ack, SNAPSHOT_REGISTER_ACK, label=f"register_ack [{path}]")

    def _assert_heartbeat_ack_contract(self, ack: Dict[str, Any], path: str) -> None:
        _check_snapshot(ack, SNAPSHOT_HEARTBEAT_ACK, label=f"heartbeat_ack [{path}]")

    # ------------------------------------------------------------------
    # /ws/android/{device_id}  — primary Android path
    # ------------------------------------------------------------------

    def test_ws_android_primary_register_ack(self, gw_client):
        device_id = f"ws-a-{uuid.uuid4().hex[:8]}"
        reg_ack, _ = _ws_register_and_heartbeat(
            gw_client, f"/ws/android/{device_id}", device_id
        )
        self._assert_register_ack_contract(reg_ack, "/ws/android/{device_id}")
        assert reg_ack["device_id"] == device_id

    def test_ws_android_primary_heartbeat_ack(self, gw_client):
        device_id = f"ws-ah-{uuid.uuid4().hex[:8]}"
        _, hb_ack = _ws_register_and_heartbeat(
            gw_client, f"/ws/android/{device_id}", device_id
        )
        self._assert_heartbeat_ack_contract(hb_ack, "/ws/android/{device_id}")
        assert hb_ack["device_id"] == device_id

    def test_ws_android_primary_version_field(self, gw_client):
        """Responses on /ws/android/{device_id} must always carry version='3.0'."""
        device_id = f"ws-av-{uuid.uuid4().hex[:8]}"
        reg_ack, hb_ack = _ws_register_and_heartbeat(
            gw_client, f"/ws/android/{device_id}", device_id
        )
        assert reg_ack.get("version") == "3.0"
        assert hb_ack.get("version") == "3.0"

    # ------------------------------------------------------------------
    # /ws/android  — fallback path with ?device_id= query param
    # ------------------------------------------------------------------

    def test_ws_android_fallback_with_device_id(self, gw_client):
        device_id = f"ws-af-{uuid.uuid4().hex[:8]}"
        reg_ack, hb_ack = _ws_register_and_heartbeat(
            gw_client, f"/ws/android?device_id={device_id}", device_id
        )
        self._assert_register_ack_contract(reg_ack, "/ws/android?device_id=")
        self._assert_heartbeat_ack_contract(hb_ack, "/ws/android?device_id=")

    def test_ws_android_fallback_auto_device_id(self, gw_client):
        """/ws/android without device_id auto-assigns one; heartbeat must still be ack'd."""
        auto_id = f"auto-{uuid.uuid4().hex[:8]}"  # we use a synthetic id in the payload
        with gw_client.websocket_connect("/ws/android") as ws:
            ws.send_text(json.dumps(_mk_v3("heartbeat", device_id=auto_id)))
            ack = ws.receive_json()
        # heartbeat_ack shape must be correct regardless of which device_id the server assigned
        _check_snapshot(ack, SNAPSHOT_HEARTBEAT_ACK, label="heartbeat_ack [/ws/android auto-id]")

    # ------------------------------------------------------------------
    # /ws/device/{device_id}  — compat alias
    # ------------------------------------------------------------------

    def test_ws_device_register_ack(self, gw_client):
        device_id = f"ws-d-{uuid.uuid4().hex[:8]}"
        reg_ack, _ = _ws_register_and_heartbeat(
            gw_client, f"/ws/device/{device_id}", device_id
        )
        self._assert_register_ack_contract(reg_ack, "/ws/device/{device_id}")
        assert reg_ack["device_id"] == device_id

    def test_ws_device_heartbeat_ack(self, gw_client):
        device_id = f"ws-dh-{uuid.uuid4().hex[:8]}"
        _, hb_ack = _ws_register_and_heartbeat(
            gw_client, f"/ws/device/{device_id}", device_id
        )
        self._assert_heartbeat_ack_contract(hb_ack, "/ws/device/{device_id}")

    def test_ws_device_version_field(self, gw_client):
        """Responses on /ws/device/{device_id} must always carry version='3.0'."""
        device_id = f"ws-dv-{uuid.uuid4().hex[:8]}"
        reg_ack, hb_ack = _ws_register_and_heartbeat(
            gw_client, f"/ws/device/{device_id}", device_id
        )
        assert reg_ack.get("version") == "3.0"
        assert hb_ack.get("version") == "3.0"

    # ------------------------------------------------------------------
    # Regression guard: type field must not change
    # ------------------------------------------------------------------

    def test_regression_register_ack_type_is_stable(self, gw_client):
        """Snapshot regression: device_register_ack type field must equal 'device_register_ack'."""
        device_id = f"ws-rg-{uuid.uuid4().hex[:8]}"
        reg_ack, _ = _ws_register_and_heartbeat(
            gw_client, f"/ws/android/{device_id}", device_id
        )
        assert reg_ack["type"] == "device_register_ack", (
            "REGRESSION: device_register response 'type' has changed from "
            f"'device_register_ack' to {reg_ack['type']!r}"
        )

    def test_regression_heartbeat_ack_type_is_stable(self, gw_client):
        """Snapshot regression: heartbeat_ack type field must equal 'heartbeat_ack'."""
        device_id = f"ws-rhb-{uuid.uuid4().hex[:8]}"
        _, hb_ack = _ws_register_and_heartbeat(
            gw_client, f"/ws/android/{device_id}", device_id
        )
        assert hb_ack["type"] == "heartbeat_ack", (
            "REGRESSION: heartbeat response 'type' has changed from "
            f"'heartbeat_ack' to {hb_ack['type']!r}"
        )

    def test_regression_message_id_unique_per_response(self, gw_client):
        """Each response must carry a distinct message_id (no static/re-used IDs)."""
        device_id = f"ws-uid-{uuid.uuid4().hex[:8]}"
        reg_ack, hb_ack = _ws_register_and_heartbeat(
            gw_client, f"/ws/android/{device_id}", device_id
        )
        ids = {reg_ack.get("message_id"), hb_ack.get("message_id")}
        assert len(ids) == 2, (
            "REGRESSION: register_ack and heartbeat_ack share the same message_id. "
            "Each response must carry a unique UUID."
        )
        for mid in ids:
            assert mid is not None
            _uuid = uuid.UUID(str(mid))  # must be a valid UUID
            assert str(_uuid) == mid


# ===========================================================================
# 5. AIP v3 MessageType completeness (contract guard)
# ===========================================================================

class TestMessageTypeContractCompleteness:
    """
    Contract: the set of MessageType values covers all message types that
    Android clients are documented to send and receive.
    """

    # Android→Server inbound types (client sends these)
    ANDROID_INBOUND = [
        "device_register",
        "heartbeat",
        "capability_report",
        "diagnostics_payload",
        "task_result",
        "task_end",         # bidirectional: client sends task_end, server also sends it
        "task_progress",
        "command_result",
        "error",            # bidirectional: both sides may send error
        "agent_ping",
        "device_status",
        "gui_screen_content",
        "vision_request",   # client initiates; server responds with vision_result
    ]

    # Server→Android outbound types (server sends these)
    ANDROID_OUTBOUND = [
        "device_register_ack",
        "heartbeat_ack",
        "capability_report_ack",
        "diagnostics_payload_ack",
        "task_assign",
        "task_end",         # bidirectional: server sends task_end to signal completion
        "command",
        "gui_click",
        "gui_swipe",
        "gui_input",
        "gui_screenshot",
        "gui_element_query",
        "error",            # bidirectional: server sends error on failure
        "vision_result",    # server response to client's vision_request
    ]

    @pytest.mark.parametrize("msg_type", ANDROID_INBOUND)
    def test_inbound_type_in_message_type_enum(self, msg_type):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        all_values = {t.value for t in MessageType}
        assert msg_type in all_values, (
            f"AIP v3 MessageType enum is missing inbound type '{msg_type}'. "
            "Add it to galaxy_gateway/protocol/aip_v3.py."
        )

    @pytest.mark.parametrize("msg_type", ANDROID_OUTBOUND)
    def test_outbound_type_in_message_type_enum(self, msg_type):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        all_values = {t.value for t in MessageType}
        assert msg_type in all_values, (
            f"AIP v3 MessageType enum is missing outbound type '{msg_type}'. "
            "Add it to galaxy_gateway/protocol/aip_v3.py."
        )


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
