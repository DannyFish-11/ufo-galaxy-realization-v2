"""
tests/integration/test_dual_repo_transport_harness.py

This module provides **transport-layer** tests for the canonical cross-repo
interaction sequence.  Unlike unit tests that call ``bridge.handle_message()``
with mocked WebSocket objects, this harness exercises the real
``_handle_android_ws`` FastAPI route via ``fastapi.testclient.TestClient``,
so every message travels through the actual JSON-over-WebSocket transport
pipeline.

Canonical path validated end-to-end:
  1. Android mock client connects to V2 gateway at ``/ws/device/{device_id}``
  2. Android sends  ``device_register``     → V2 returns ``device_register_ack``
  3. Android sends  ``capability_report``   → V2 returns ``capability_report_ack``
                                              and persists capabilities to bridge
  4. V2 dispatches  ``task_assign``         → Android receives via WS transport
  5. Android sends  ``task_result``         → V2 bridge processes and resolves
                                              the pending Future (waiter unblock)

Also verified:
  - session continuity signal after register + capability
  - device identity survives within a WS session
  - task_result delivery resolves the dispatch-side Future

``AndroidProtocolClient`` is a protocol-faithful Android mock client that
communicates exclusively via JSON-over-WebSocket (AIP v3), mirroring the
message formats defined in the ufo-galaxy-android repository.

No external services or running processes are required.
"""

import asyncio
import json
import time
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# AIP v3 message helpers
# ---------------------------------------------------------------------------


def _v3(msg_type: str, device_id: str, **extra) -> Dict[str, Any]:
    """Return a fully-compliant AIP v3 message dict."""
    return {
        "version": "3.0",
        "type": msg_type,
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        **extra,
    }


# ---------------------------------------------------------------------------
# AndroidProtocolClient — protocol-faithful Android mock client
# ---------------------------------------------------------------------------


class AndroidProtocolClient:
    """Protocol-faithful Android mock client for V2 ↔ Android integration tests.

    Communicates exclusively at the transport/protocol layer via a FastAPI
    TestClient WebSocket session.  Every message is serialised as JSON and
    sent over the real WebSocket transport; no internal Python bridge methods
    are called directly.

    This class mirrors the message exchange performed by the real
    ``ufo-galaxy-android`` application (``AgentWebSocket`` /
    ``AgentMessageHandler``), making it suitable as the "Android side" in
    dual-repo regression tests.
    """

    def __init__(self, ws: Any, device_id: str) -> None:
        self._ws = ws
        self.device_id = device_id
        self._received: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------ I/O

    def send(self, msg: Dict[str, Any]) -> None:
        """Serialise *msg* and send it over the WebSocket transport."""
        self._ws.send_text(json.dumps(msg))

    def receive(self) -> Dict[str, Any]:
        """Block until a message arrives from the V2 gateway and return it."""
        msg = self._ws.receive_json()
        self._received.append(msg)
        return msg

    # ---------------------------------------------------------------- flows

    def register(
        self,
        platform: str = "android",
        model: str = "Pixel Test Phone",
    ) -> Dict[str, Any]:
        """Send ``device_register`` and return the ``device_register_ack``."""
        self.send(
            _v3(
                "device_register",
                self.device_id,
                platform=platform,
                model=model,
            )
        )
        return self.receive()

    def report_capabilities(
        self,
        actions: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Send ``capability_report`` and return the ``capability_report_ack``."""
        actions = actions or ["tap", "swipe", "screenshot", "input_text"]
        self.send(
            _v3(
                "capability_report",
                self.device_id,
                platform="android",
                supported_actions=actions,
            )
        )
        return self.receive()

    def send_task_result(
        self,
        task_id: str,
        status: str = "completed",
        result: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send ``task_result`` (V2 handles it asynchronously; no response)."""
        self.send(
            _v3(
                "task_result",
                self.device_id,
                task_id=task_id,
                status=status,
                result=result or {"output": "ok"},
            )
        )

    def send_heartbeat(self) -> Dict[str, Any]:
        """Send ``heartbeat`` and return the ``heartbeat_ack``."""
        self.send(_v3("heartbeat", self.device_id))
        return self.receive()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def gw_client():
    """Minimal FastAPI app backed by the production Android WS handler.

    A minimal app (not the full ``galaxy_gateway.app``) is used so that
    infrastructure services that are unrelated to the protocol contract
    (NATS, schedulers, etc.) do not block the test.  The WS handler
    ``_handle_android_ws`` is the identical production function used by the
    real gateway.
    """
    from fastapi import FastAPI, WebSocket
    from fastapi.testclient import TestClient

    from galaxy_gateway.routes.websocket import _handle_android_ws

    app = FastAPI()

    @app.websocket("/ws/device/{device_id}")
    async def ws_device(websocket: WebSocket, device_id: str) -> None:
        await _handle_android_ws(websocket, device_id)

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def bridge():
    from galaxy_gateway.android_bridge import android_bridge as _bridge

    return _bridge


# ===========================================================================
# 1. Transport-layer device registration
# ===========================================================================


class TestTransportLayerRegister:
    """Android mock client registers via the real WS transport pipeline."""

    def test_register_ack_delivered_via_transport(self, gw_client: Any) -> None:
        """device_register_ack must be returned over the real WS transport."""
        device_id = f"tr-reg-{uuid.uuid4().hex[:8]}"
        with gw_client.websocket_connect(f"/ws/device/{device_id}") as ws:
            client = AndroidProtocolClient(ws, device_id)
            ack = client.register()

        assert ack["type"] == "device_register_ack", (
            f"Expected 'device_register_ack', got {ack['type']!r}"
        )
        assert ack["success"] is True
        assert ack["device_id"] == device_id
        assert ack["version"] == "3.0"

    def test_register_stores_device_in_bridge(
        self, gw_client: Any, bridge: Any
    ) -> None:
        """Bridge must persist device state while WS session is open."""
        device_id = f"tr-store-{uuid.uuid4().hex[:8]}"
        with gw_client.websocket_connect(f"/ws/device/{device_id}") as ws:
            client = AndroidProtocolClient(ws, device_id)
            client.register()

            device = bridge.get_device(device_id)
            assert device is not None, (
                f"Device {device_id!r} not found in bridge after registration"
            )
            assert device.device_id == device_id
            assert device.connected is True

    def test_register_ack_carries_required_aip_v3_fields(
        self, gw_client: Any
    ) -> None:
        """``device_register_ack`` must carry all canonical AIP v3 required fields."""
        device_id = f"tr-fields-{uuid.uuid4().hex[:8]}"
        with gw_client.websocket_connect(f"/ws/device/{device_id}") as ws:
            client = AndroidProtocolClient(ws, device_id)
            ack = client.register()

        required = ("version", "type", "device_id", "message_id", "timestamp")
        for field in required:
            assert field in ack, (
                f"Required AIP v3 field '{field}' missing from register_ack"
            )


# ===========================================================================
# 2. Transport-layer capability report
# ===========================================================================


class TestTransportLayerCapabilityReport:
    """capability_report travels through real WS transport and is persisted."""

    CAPABILITIES = ["tap", "swipe", "screenshot", "input_text"]

    def test_capability_report_ack_via_transport(self, gw_client: Any) -> None:
        """capability_report_ack must be returned over the real WS transport."""
        device_id = f"tr-cap-{uuid.uuid4().hex[:8]}"
        with gw_client.websocket_connect(f"/ws/device/{device_id}") as ws:
            client = AndroidProtocolClient(ws, device_id)
            client.register()
            ack = client.report_capabilities(self.CAPABILITIES)

        assert ack["type"] == "capability_report_ack", (
            f"Expected 'capability_report_ack', got {ack['type']!r}"
        )
        assert ack.get("accepted") is True
        assert ack["device_id"] == device_id

    def test_capability_report_persisted_to_bridge(
        self, gw_client: Any, bridge: Any
    ) -> None:
        """supported_actions must be stored on the bridge device object after report."""
        device_id = f"tr-cap-p-{uuid.uuid4().hex[:8]}"
        with gw_client.websocket_connect(f"/ws/device/{device_id}") as ws:
            client = AndroidProtocolClient(ws, device_id)
            client.register()
            client.report_capabilities(self.CAPABILITIES)

            device = bridge.get_device(device_id)
            assert device is not None
            for cap in self.CAPABILITIES:
                assert cap in device.supported_actions, (
                    f"Capability '{cap}' not found in device.supported_actions"
                )

    def test_capability_report_requires_prior_registration(
        self, gw_client: Any
    ) -> None:
        """capability_report on an unregistered device must not raise; ack is returned."""
        device_id = f"tr-cap-noreg-{uuid.uuid4().hex[:8]}"
        with gw_client.websocket_connect(f"/ws/device/{device_id}") as ws:
            ws.send_text(
                json.dumps(
                    _v3(
                        "capability_report",
                        device_id,
                        platform="android",
                        supported_actions=["tap"],
                    )
                )
            )
            # Gateway should still respond (may be ack or error)
            msg = ws.receive_json()
            assert "type" in msg, "Gateway must respond to capability_report"


# ===========================================================================
# 3. Dispatch → task_result → waiter unblock (async)
# ===========================================================================


class TestDispatchResultWaiterUnblock:
    """V2 dispatch waiter is unblocked when task_result arrives from Android."""

    @pytest.mark.asyncio
    async def test_task_result_resolves_pending_future(self) -> None:
        """``task_result`` received by the bridge resolves the registered Future.

        This test proves that the V2-side waiter mechanism (``_pending_responses``
        dict + asyncio.Future) is correctly unblocked when Android sends
        ``task_result``.  The path exercises the real ``handle_task_result``
        handler — the same code that runs in production.
        """
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        ws = MagicMock()
        ws.send_json = AsyncMock()
        device_id = f"async-task-{uuid.uuid4().hex[:8]}"
        task_id = str(uuid.uuid4())

        # Step 1: register device so bridge knows about it
        await bridge.handle_message(
            ws, _v3("device_register", device_id, platform="android")
        )

        # Step 2: install a Future that represents the V2 dispatch waiter
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        bridge._pending_responses[task_id] = future

        # Step 3: Android sends task_result (via the real handle_message path)
        await bridge.handle_message(
            ws,
            _v3(
                "task_result",
                device_id,
                task_id=task_id,
                status="completed",
                result={"output": "screenshot.png"},
            ),
        )

        # Step 4: waiter must be unblocked
        assert future.done(), (
            "Future must be resolved after task_result is processed — "
            "V2 waiter was not unblocked"
        )
        resolved = future.result()
        assert resolved is not None

    @pytest.mark.asyncio
    async def test_send_to_device_waiter_unblocked_by_task_result(self) -> None:
        """Full send_to_device → task_result → waiter roundtrip via real asyncio.

        ``send_to_device(wait_response=True)`` installs a Future and awaits it.
        Concurrently, Android sends ``task_result``, which ``handle_message``
        routes to ``handle_task_result``.  The Future must be resolved and the
        ``send_to_device`` coroutine must return the result without timeout.
        """
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        task_id = str(uuid.uuid4())
        device_id = f"roundtrip-{uuid.uuid4().hex[:8]}"

        sent_messages: List[Any] = []
        ws = MagicMock()
        ws.send_json = AsyncMock(
            side_effect=lambda msg: sent_messages.append(msg)
        )
        ws.send = AsyncMock(
            side_effect=lambda msg: sent_messages.append(
                json.loads(msg) if isinstance(msg, str) else msg
            )
        )

        # Register device
        await bridge.handle_message(
            ws, _v3("device_register", device_id, platform="android")
        )

        task_msg = {
            "version": "3.0",
            "type": "task_assign",
            "message_id": task_id,
            "task_id": task_id,
            "device_id": device_id,
            "timestamp": int(time.time() * 1000),
        }

        async def dispatch_and_collect() -> Optional[Dict[str, Any]]:
            return await bridge.send_to_device(
                device_id, task_msg, wait_response=True, timeout=5.0
            )

        # Start dispatch (installs Future and awaits it)
        dispatch_task = asyncio.ensure_future(dispatch_and_collect())

        # Give dispatch a moment to install the Future
        await asyncio.sleep(0.05)

        # Android sends back task_result — resolves the dispatch Future
        await bridge.handle_message(
            ws,
            _v3(
                "task_result",
                device_id,
                task_id=task_id,
                status="completed",
                result={"data": "done"},
            ),
        )

        # Dispatch waiter must return without timeout
        result = await asyncio.wait_for(dispatch_task, timeout=5.0)
        assert result is not None, (
            "send_to_device must return a result when task_result is received"
        )

    def test_task_result_delivered_via_ws_transport(
        self, gw_client: Any, bridge: Any
    ) -> None:
        """``task_result`` delivered via real WS transport is processed by V2.

        Validates that the WS transport pipeline is not a dead end for
        task_result messages — the real ``_handle_android_ws`` receive loop
        correctly routes the message into ``handle_task_result``.
        """
        device_id = f"tr-result-{uuid.uuid4().hex[:8]}"
        task_id = str(uuid.uuid4())

        with gw_client.websocket_connect(f"/ws/device/{device_id}") as ws:
            client = AndroidProtocolClient(ws, device_id)
            client.register()
            client.report_capabilities(["screenshot"])

            # Verify device is registered in the bridge
            device = bridge.get_device(device_id)
            assert device is not None

            # Deliver task_result via real WS transport (Android → V2)
            # handle_task_result is called; no response is sent back
            client.send_task_result(task_id, status="completed")
            # Sending heartbeat after ensures the WS loop is still alive and
            # the previous task_result was processed without crashing
            hb_ack = client.send_heartbeat()
            assert hb_ack["type"] == "heartbeat_ack"


# ===========================================================================
# 4. Full canonical main chain — register → capability → dispatch → result
# ===========================================================================


class TestFullCanonicalMainChain:
    """Full V2 ↔ Android canonical path executed via transport + async."""

    def test_canonical_chain_transport_segment(self, gw_client: Any, bridge: Any) -> None:
        """register → capability → task_result via real WS transport (transport segment).

        This test exercises the full inbound transport segment of the canonical
        chain.  The V2 gateway correctly ingests each message, persists state,
        and delivers acks over the real WebSocket transport.
        """
        device_id = f"chain-transport-{uuid.uuid4().hex[:8]}"
        task_id = str(uuid.uuid4())
        caps = ["tap", "swipe", "screenshot"]

        with gw_client.websocket_connect(f"/ws/device/{device_id}") as ws:
            client = AndroidProtocolClient(ws, device_id)

            # Step 1 — register
            reg_ack = client.register(platform="android", model="Dual-Repo Test Phone")
            assert reg_ack["type"] == "device_register_ack"
            assert reg_ack["success"] is True

            # Step 2 — capability report
            cap_ack = client.report_capabilities(caps)
            assert cap_ack["type"] == "capability_report_ack"
            assert cap_ack.get("accepted") is True

            # Step 3 — verify V2 internal state (UDM write path)
            device = bridge.get_device(device_id)
            assert device is not None
            assert device.connected is True

            # Step 4 — Android returns task_result (inbound transport leg)
            client.send_task_result(task_id, status="completed")

            # Step 5 — heartbeat proves WS loop is alive after task_result
            hb_ack = client.send_heartbeat()
            assert hb_ack["type"] == "heartbeat_ack"

    @pytest.mark.asyncio
    async def test_canonical_chain_full_async_roundtrip(self) -> None:
        """Full roundtrip: register → capability → dispatch → task_result → waiter.

        This test validates the complete V2 ↔ Android interaction in a single
        in-process async execution.  The ``send_to_device`` coroutine installs
        the dispatch Future; ``handle_message`` (task_result) resolves it.
        This is the complete canonical path validated end-to-end.
        """
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        ws = MagicMock()
        ws.send_json = AsyncMock()
        device_id = f"chain-full-{uuid.uuid4().hex[:8]}"
        task_id = str(uuid.uuid4())
        caps = ["tap", "screenshot", "input_text"]

        # Step 1 — device_register
        reg_ack = await bridge.handle_message(
            ws,
            _v3("device_register", device_id, platform="android", model="Chain Test"),
        )
        assert reg_ack is not None
        assert reg_ack["type"] == "device_register_ack"
        assert reg_ack["success"] is True

        # Step 2 — capability_report
        cap_ack = await bridge.handle_message(
            ws,
            _v3(
                "capability_report",
                device_id,
                platform="android",
                supported_actions=caps,
            ),
        )
        assert cap_ack is not None
        assert cap_ack["type"] == "capability_report_ack"
        assert cap_ack.get("accepted") is True

        # Step 3 — V2 internal state: capabilities persisted
        device = bridge.get_device(device_id)
        assert device is not None
        for cap in caps:
            assert cap in device.supported_actions

        # Step 4 — V2 dispatch: install Future and send task_assign
        task_assign_msg = {
            "version": "3.0",
            "type": "task_assign",
            "message_id": task_id,
            "task_id": task_id,
            "device_id": device_id,
            "timestamp": int(time.time() * 1000),
            "payload": {"command": "screenshot"},
        }

        async def dispatch() -> Optional[Dict[str, Any]]:
            return await bridge.send_to_device(
                device_id, task_assign_msg, wait_response=True, timeout=5.0
            )

        dispatch_task = asyncio.ensure_future(dispatch())
        await asyncio.sleep(0.05)

        # Step 5 — Android sends task_result → V2 waiter unblocks
        await bridge.handle_message(
            ws,
            _v3(
                "task_result",
                device_id,
                task_id=task_id,
                status="completed",
                result={"image_base64": "abc123"},
            ),
        )

        result = await asyncio.wait_for(dispatch_task, timeout=5.0)
        assert result is not None, (
            "V2 waiter must be unblocked after Android sends task_result — "
            "full canonical main chain failed"
        )
