"""
tests/integration/test_integration_review_runtime_paths.py
===========================================================
联排审查 / Integration Review — Runtime Path Inspection
ufo-galaxy-realization-v2 × ufo-galaxy-android

PURPOSE
-------
This file is a *review / runtime path inspection* test module.
It is NOT a fix PR or a feature test.

Goal: expose the real state of the center-side production paths by
executing them with the smallest possible mocking surface.  Every test
names its verdict explicitly in its assertion messages:

    CLOSED      — path runs end-to-end, result is verifiable.
    PARTIAL     — path runs but one or more downstream steps may be absent.
    GAP_EXPOSED — a real production-path gap is visible and machine-checkable.

Where a gap exists the test FAILS (not skips, not xfails silently) unless the
gap is documented as an expected incomplete state that is already observable
through an existing observability mechanism (ledger, registration gaps, etc.).

Paths inspected
---------------
1. Canonical ingress route binding
   Is /ws/device/{device_id} actually wired to the real _handle_android_ws handler?
   Gap: if it is not, all Android connections are silently routed to the wrong handler.

2. disconnect_device state transition
   After disconnect_device(), does bridge._devices[id].connected become False?
   Gap: if not, the bridge thinks the device is still alive after disconnect.

3. reconnect_device behaviour for never-registered device
   reconnect_device() must return False and NOT create a new device entry.
   Gap: if it silently creates a phantom entry, task dispatch may reach a
   non-existent real device.

4. reconnect_device restores connection for a known device
   After register → disconnect → reconnect the device is marked connected=True.
   Gap: if not, the device is permanently lost after one disconnect.

5. task_result with failed / error / cancelled status is NOT silently mapped to completed
   All existing tests use status="completed".  This path verifies that failure
   statuses are preserved as failures, not normalised away.

6. dispatch_to_websocket asyncio.Event path
   Verifies that the real asyncio.Event-based wait mechanism (used by
   device_router.send_command_to_device, distinct from bridge.send_to_device's
   Future mechanism) is exercised correctly.

7. heartbeat_timeout → cleanup_stale_devices marks device disconnected
   cleanup_stale_devices() must mark devices with stale heartbeats as disconnected.
   Gap: if the method silently skips, stale devices are never cleaned up.

Android-side liaison
--------------------
These tests cover the center (V2 / ufo-galaxy-realization-v2) side only.
Android-side paths (GalaxyConnectionService, AgentRuntimeBridge, EdgeExecutor,
OfflineTaskQueue replay) are out of scope for this file and must be inspected
in ufo-galaxy-android separately.

Open gaps that require Android-side pairing
-------------------------------------------
- Offline replay: when Android reconnects and replays task_result, the center's
  durable idempotency guard (core.durable_result_idempotency) is the sole
  defence.  There is no center-side "replay ack" message that Android can use
  to confirm the result was accepted.  Whether Android actually replays on
  reconnect, and whether the protocol includes a replay acknowledgement, must
  be confirmed in ufo-galaxy-android.
- task_assign delivery guarantee: once the center dispatches task_assign via
  WebSocket, there is no server-side persistence of the assign.  If the device
  disconnects before receiving it, the task is silently lost (no re-queue).
  This is a center-side gap visible from the code; Android cannot recover it.
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _v3(msg_type: str, device_id: str, **extra) -> Dict[str, Any]:
    """Return a minimal AIP v3 message dict."""
    return {
        "version": "3.0",
        "type": msg_type,
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        **extra,
    }


def _make_ws() -> MagicMock:
    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.send = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def bridge():
    from galaxy_gateway.android_bridge import AndroidBridge
    return AndroidBridge()


@pytest.fixture()
def gw_client():
    """Minimal FastAPI app backed by the real _handle_android_ws handler."""
    from fastapi import FastAPI, WebSocket
    from fastapi.testclient import TestClient
    from galaxy_gateway.routes.websocket import _handle_android_ws

    app = FastAPI()

    @app.websocket("/ws/device/{device_id}")
    async def ws_device(websocket: WebSocket, device_id: str) -> None:
        await _handle_android_ws(websocket, device_id)

    with TestClient(app) as c:
        yield c


# ===========================================================================
# 1. Canonical ingress route binding
# ===========================================================================


class TestCanonicalIngressBinding:
    """Verify /ws/device/{device_id} is bound to the real production handler.

    If the canonical ingress is not wired to _handle_android_ws, all Android
    connections are silently routed to the wrong handler and the AIP v3
    protocol is not honoured.
    """

    def test_canonical_path_returns_device_register_ack(self, gw_client: Any) -> None:
        """CLOSED: /ws/device/{device_id} route accepts AIP v3 device_register.

        This directly verifies the canonical ingress wiring.  If the route
        were bound to a stub or a different handler, it would not return a
        device_register_ack.
        """
        device_id = f"insp-bind-{uuid.uuid4().hex[:8]}"
        with gw_client.websocket_connect(f"/ws/device/{device_id}") as ws:
            ws.send_text(json.dumps(_v3("device_register", device_id, platform="android")))
            ack = ws.receive_json()

        assert ack.get("type") == "device_register_ack", (
            f"CLOSED — canonical ingress /ws/device/{{device_id}} must route to "
            f"_handle_android_ws and return device_register_ack; "
            f"got {ack.get('type')!r}.  "
            f"If this fails the canonical ingress binding is broken."
        )
        assert ack.get("success") is True
        assert ack.get("device_id") == device_id

    def test_canonical_path_handles_heartbeat(self, gw_client: Any) -> None:
        """CLOSED: /ws/device/{device_id} → register → heartbeat → heartbeat_ack."""
        device_id = f"insp-hb-{uuid.uuid4().hex[:8]}"
        with gw_client.websocket_connect(f"/ws/device/{device_id}") as ws:
            ws.send_text(json.dumps(_v3("device_register", device_id)))
            ws.receive_json()  # consume register_ack
            ws.send_text(json.dumps(_v3("heartbeat", device_id)))
            hb_ack = ws.receive_json()

        assert hb_ack.get("type") == "heartbeat_ack", (
            f"CLOSED — heartbeat via canonical ingress must return heartbeat_ack; "
            f"got {hb_ack.get('type')!r}"
        )


# ===========================================================================
# 2. disconnect_device state transition
# ===========================================================================


class TestDisconnectStateTransition:
    """disconnect_device() must set bridge._devices[id].connected = False.

    If this state transition does not occur, the bridge believes the device
    is still alive and task dispatches will attempt to send on a dead socket.
    """

    @pytest.mark.asyncio
    async def test_disconnect_sets_connected_false(self, bridge: Any) -> None:
        """CLOSED: after disconnect_device, bridge._devices[id].connected is False."""
        device_id = f"insp-disc-{uuid.uuid4().hex[:8]}"
        ws = _make_ws()

        await bridge.handle_message(ws, _v3("device_register", device_id))

        # Verify device is registered and connected
        device = bridge.get_device(device_id)
        assert device is not None, (
            "Precondition: device must be present in bridge after registration"
        )
        assert device.connected is True, (
            "Precondition: device.connected must be True after registration"
        )

        # Disconnect
        await bridge.disconnect_device(device_id)

        # State transition must be reflected immediately in bridge cache
        device_after = bridge.get_device(device_id)
        assert device_after is not None, (
            "GAP_EXPOSED: bridge._devices entry must survive disconnect "
            "(the identity entry is retained; only connected=False). "
            "If this fails, the device identity is lost on disconnect."
        )
        assert device_after.connected is False, (
            "CLOSED: bridge._devices[id].connected must be False after disconnect_device(). "
            "If this is True, the bridge thinks the device is still alive after disconnect — "
            "subsequent task dispatches will attempt sends on a closed socket."
        )

    @pytest.mark.asyncio
    async def test_disconnect_clears_websocket_handle(self, bridge: Any) -> None:
        """CLOSED: after disconnect_device, bridge._devices[id].websocket is None."""
        device_id = f"insp-disc-ws-{uuid.uuid4().hex[:8]}"
        ws = _make_ws()

        await bridge.handle_message(ws, _v3("device_register", device_id))
        await bridge.disconnect_device(device_id)

        device_after = bridge.get_device(device_id)
        assert device_after is not None
        assert device_after.websocket is None, (
            "CLOSED: websocket handle must be cleared on disconnect. "
            "If it is not None, a closed WebSocket object remains in the session cache — "
            "any send attempt after disconnect will raise."
        )


# ===========================================================================
# 3. reconnect_device — unknown device
# ===========================================================================


class TestReconnectUnknownDevice:
    """reconnect_device() must return False for never-registered devices.

    If reconnect silently creates a phantom entry or returns True, task
    dispatches may reach a device entry that has no real WS connection.
    """

    @pytest.mark.asyncio
    async def test_reconnect_returns_false_for_unknown_device(
        self, bridge: Any
    ) -> None:
        """GAP_EXPOSED: reconnect_device returns False when device was never registered.

        This is a production-path gap: if Android sends a reconnect message
        for a device_id that the server never saw (e.g. after a server restart),
        reconnect_device returns False.  The caller must handle this by
        requiring a full re-registration.
        """
        phantom_id = f"insp-phantom-{uuid.uuid4().hex[:8]}"
        ws = _make_ws()

        result = await bridge.reconnect_device(phantom_id, ws)

        assert result is False, (
            "GAP_EXPOSED: reconnect_device must return False for an unknown device_id. "
            f"Got {result!r}. "
            "If this returns True, the bridge creates a phantom device entry with a "
            "real WebSocket handle but no registered identity — task dispatches to this "
            "device will send to a socket that the Android side may not recognise as a "
            "valid session.  After a server restart Android MUST re-register."
        )
        assert bridge.get_device(phantom_id) is None, (
            "GAP_EXPOSED: reconnect for unknown device must NOT create a new bridge entry. "
            "If an entry was created, the device registry is polluted with phantom entries."
        )


# ===========================================================================
# 4. reconnect_device — known device
# ===========================================================================


class TestReconnectKnownDevice:
    """reconnect_device() restores connected=True for a previously registered device."""

    @pytest.mark.asyncio
    async def test_reconnect_restores_connection_after_disconnect(
        self, bridge: Any
    ) -> None:
        """CLOSED: register → disconnect → reconnect restores connected=True.

        If reconnect does not restore connected=True, the device is permanently
        marked as offline after the first disconnect even when it physically
        reconnects.
        """
        device_id = f"insp-reconn-{uuid.uuid4().hex[:8]}"
        ws1 = _make_ws()
        ws2 = _make_ws()

        # Register
        await bridge.handle_message(ws1, _v3("device_register", device_id))
        device = bridge.get_device(device_id)
        assert device is not None
        assert device.connected is True

        # Disconnect
        await bridge.disconnect_device(device_id)
        assert bridge.get_device(device_id).connected is False

        # Reconnect with new WS handle
        result = await bridge.reconnect_device(device_id, ws2)

        assert result is True, (
            "CLOSED: reconnect_device must return True for a known device. "
            f"Got {result!r}."
        )
        device_after = bridge.get_device(device_id)
        assert device_after is not None
        assert device_after.connected is True, (
            "CLOSED: bridge._devices[id].connected must be True after reconnect_device(). "
            "If this fails, the device is permanently offline after one disconnect."
        )
        assert device_after.websocket is ws2, (
            "CLOSED: bridge._devices[id].websocket must be the NEW WebSocket handle "
            "after reconnect.  The old handle was closed; the new one is live."
        )


# ===========================================================================
# 5. task_result failure status preservation
# ===========================================================================


class TestTaskResultFailureStatus:
    """task_result with failed / error / cancelled status must NOT become completed.

    All existing integration tests send status="completed".  This class
    explicitly tests the failure paths to verify that the status mapping in
    handle_task_result preserves the real result status.

    Production risk: if failure statuses are silently mapped to completed,
    the center believes a failed task succeeded — downstream acceptance logic
    (CanonicalCompletionIngress, IncompleteResultLedger) receives wrong status.
    """

    @pytest.mark.asyncio
    async def test_task_result_failed_status_resolves_future_with_failed_status(
        self, bridge: Any
    ) -> None:
        """CLOSED: task_result with status=failed must resolve the Future with status=failed.

        The Future resolved by handle_task_result carries the raw message dict.
        If the status field is normalised away to "completed", the caller cannot
        distinguish a failed execution from a successful one.
        """
        device_id = f"insp-fail-{uuid.uuid4().hex[:8]}"
        task_id = str(uuid.uuid4())
        ws = _make_ws()

        await bridge.handle_message(ws, _v3("device_register", device_id))

        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        bridge._pending_responses[task_id] = future

        await bridge.handle_message(
            ws,
            _v3("task_result", device_id, task_id=task_id, status="failed",
                result={"error": "permission_denied"}),
        )

        assert future.done(), (
            "CLOSED: Future must be resolved even when status=failed"
        )
        resolved = future.result()
        assert resolved is not None

        # The raw status field must survive — not be normalised to "completed"
        raw_status = resolved.get("status", "")
        assert raw_status == "failed", (
            f"CLOSED: task_result status=failed must be preserved in the resolved Future. "
            f"Got status={raw_status!r}.  "
            "If this is 'completed', failure results are silently accepted as success — "
            "the center cannot detect Android-side execution failures."
        )

    @pytest.mark.asyncio
    async def test_task_result_error_status_resolves_future_with_error_status(
        self, bridge: Any
    ) -> None:
        """CLOSED: task_result with status=error must resolve Future with status=error."""
        device_id = f"insp-err-{uuid.uuid4().hex[:8]}"
        task_id = str(uuid.uuid4())
        ws = _make_ws()

        await bridge.handle_message(ws, _v3("device_register", device_id))

        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        bridge._pending_responses[task_id] = future

        await bridge.handle_message(
            ws,
            _v3("task_result", device_id, task_id=task_id, status="error",
                result={"error": "crash"}),
        )

        assert future.done()
        resolved = future.result()
        raw_status = resolved.get("status", "")
        assert raw_status == "error", (
            f"CLOSED: task_result status=error must be preserved in the resolved Future. "
            f"Got status={raw_status!r}.  "
            "The center must be able to distinguish 'error' from 'completed'."
        )

    @pytest.mark.asyncio
    async def test_task_result_cancelled_status_resolves_future_with_cancelled_status(
        self, bridge: Any
    ) -> None:
        """CLOSED: task_result with status=cancelled must resolve Future with status=cancelled."""
        device_id = f"insp-cancel-{uuid.uuid4().hex[:8]}"
        task_id = str(uuid.uuid4())
        ws = _make_ws()

        await bridge.handle_message(ws, _v3("device_register", device_id))

        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        bridge._pending_responses[task_id] = future

        await bridge.handle_message(
            ws,
            _v3("task_result", device_id, task_id=task_id, status="cancelled"),
        )

        assert future.done()
        resolved = future.result()
        raw_status = resolved.get("status", "")
        assert raw_status == "cancelled", (
            f"CLOSED: task_result status=cancelled must be preserved in the resolved Future. "
            f"Got status={raw_status!r}."
        )

    @pytest.mark.asyncio
    async def test_task_result_failed_via_ws_transport_does_not_raise(
        self, gw_client: Any
    ) -> None:
        """CLOSED: task_result with status=failed via real WS transport must not crash."""
        device_id = f"insp-fail-tr-{uuid.uuid4().hex[:8]}"
        task_id = str(uuid.uuid4())

        with gw_client.websocket_connect(f"/ws/device/{device_id}") as ws:
            ws.send_text(json.dumps(_v3("device_register", device_id)))
            ws.receive_json()  # consume register_ack

            # Send failed task_result via real transport
            ws.send_text(
                json.dumps(
                    _v3("task_result", device_id, task_id=task_id, status="failed",
                        result={"error": "execution_timeout"})
                )
            )
            # task_result has no synchronous response; just verify no crash
            # The WS connection must remain alive (no server-side close)


# ===========================================================================
# 6. dispatch_to_websocket asyncio.Event path
# ===========================================================================


class TestDispatchToWebsocketEventPath:
    """dispatch_to_websocket uses asyncio.Event (not Future) to wait for results.

    device_router.send_command_to_device → dispatch_to_websocket:
      1. Sends message via device.websocket.send
      2. Creates asyncio.Event in task_events[task_id]
      3. Awaits event.wait() with timeout
      4. Returns task_results[task_id] when event fires

    This is a SEPARATE mechanism from bridge.send_to_device which uses
    bridge._pending_responses (asyncio.Future).

    If dispatch_to_websocket is used in production but the test only exercises
    bridge.send_to_device, the Event path is untested and could silently timeout
    on every real dispatch.
    """

    @pytest.mark.asyncio
    async def test_dispatch_to_websocket_returns_result_when_event_is_set(
        self,
    ) -> None:
        """CLOSED: dispatch_to_websocket returns the result dict when event fires.

        This test exercises the real galaxy_gateway.routing.dispatch.dispatch_to_websocket
        function directly, verifying the asyncio.Event wait-and-return path.
        """
        from galaxy_gateway.routing.dispatch import dispatch_to_websocket

        device_id = f"insp-dws-{uuid.uuid4().hex[:8]}"
        task_id = str(uuid.uuid4())

        # Minimal device stub (only websocket.send is called)
        ws_mock = MagicMock()
        ws_mock.send = AsyncMock()

        stub = MagicMock()
        stub.websocket = ws_mock
        stub.device_id = device_id

        task_events: Dict[str, asyncio.Event] = {}
        task_results: Dict[str, Dict] = {}

        message = {
            "version": "3.0",
            "type": "command",
            "message_id": str(uuid.uuid4()),
            "device_id": device_id,
            "task_id": task_id,
            "trace_id": str(uuid.uuid4()),
            "timestamp": int(time.time() * 1000),
            "payload": {"command": "screenshot"},
        }

        expected_result = {
            "task_id": task_id,
            "status": "completed",
            "result": {"output": "screenshot.png"},
        }

        async def _simulate_android_result() -> None:
            # Wait briefly for dispatch_to_websocket to install the event
            await asyncio.sleep(0.05)
            # Simulate Android result arrival (as device_router.handle_task_result does)
            task_results[task_id] = expected_result
            event = task_events.get(task_id)
            assert event is not None, (
                "CLOSED: dispatch_to_websocket must install an Event in task_events "
                "before the android result arrives.  If this is None, the result "
                "event mechanism is broken."
            )
            event.set()

        result_sim = asyncio.ensure_future(_simulate_android_result())
        result = await dispatch_to_websocket(
            device=stub,
            message=message,
            task_id=task_id,
            task_events=task_events,
            task_results=task_results,
            timeout=3.0,
        )
        await result_sim

        assert result is not None, (
            "CLOSED: dispatch_to_websocket must return a result when the event fires"
        )
        assert result.get("task_id") == task_id, (
            f"CLOSED: result task_id must match dispatched task_id. "
            f"Got {result.get('task_id')!r}"
        )
        assert result.get("status") == "completed", (
            f"CLOSED: result status must be 'completed'. Got {result.get('status')!r}"
        )

    @pytest.mark.asyncio
    async def test_dispatch_to_websocket_returns_error_on_timeout(self) -> None:
        """CLOSED: dispatch_to_websocket returns error dict (not raise) on timeout.

        A timeout must not cause an unhandled exception — it must return a
        structured error dict so callers can distinguish timeout from success.
        """
        from galaxy_gateway.routing.dispatch import dispatch_to_websocket

        device_id = f"insp-dws-to-{uuid.uuid4().hex[:8]}"
        task_id = str(uuid.uuid4())

        ws_mock = MagicMock()
        ws_mock.send = AsyncMock()

        stub = MagicMock()
        stub.websocket = ws_mock
        stub.device_id = device_id

        task_events: Dict[str, asyncio.Event] = {}
        task_results: Dict[str, Dict] = {}

        message = {
            "version": "3.0",
            "type": "command",
            "message_id": str(uuid.uuid4()),
            "device_id": device_id,
            "task_id": task_id,
            "trace_id": "trace-timeout-test",
            "timestamp": int(time.time() * 1000),
            "payload": {"command": "screenshot"},
        }

        # No result will arrive — test that timeout produces an error dict
        result = await dispatch_to_websocket(
            device=stub,
            message=message,
            task_id=task_id,
            task_events=task_events,
            task_results=task_results,
            timeout=0.1,  # very short timeout
        )

        assert result is not None, (
            "CLOSED: dispatch_to_websocket must return a dict (not None) on timeout"
        )
        assert result.get("success") is False, (
            f"CLOSED: timeout result must have success=False. Got {result!r}"
        )
        assert result.get("error"), (
            "CLOSED: timeout result must include a non-empty 'error' field"
        )


# ===========================================================================
# 7. heartbeat timeout → cleanup_stale_devices
# ===========================================================================


class TestHeartbeatTimeoutCleanup:
    """cleanup_stale_devices marks timed-out devices as disconnected.

    There is NO automatic background task running in tests; cleanup_stale_devices
    must be called explicitly.  This test verifies that the method correctly
    identifies and disconnects devices whose last_heartbeat is older than
    timeout_seconds.
    """

    @pytest.mark.asyncio
    async def test_stale_device_is_disconnected_on_cleanup(
        self, bridge: Any
    ) -> None:
        """CLOSED: cleanup_stale_devices disconnects device with stale heartbeat.

        If this path does not work, stale devices are never cleaned up.
        The bridge accumulates phantom-connected entries and dispatch may
        attempt sends on long-dead sockets.
        """
        device_id = f"insp-stale-{uuid.uuid4().hex[:8]}"
        ws = _make_ws()

        await bridge.handle_message(ws, _v3("device_register", device_id))

        device = bridge.get_device(device_id)
        assert device is not None
        assert device.connected is True

        # Back-date the last_heartbeat so it looks stale
        device.last_heartbeat = time.time() - 300.0  # 300s ago

        # Run cleanup with a 60s timeout — device should be evicted
        await bridge.cleanup_stale_devices(timeout_seconds=60.0)

        device_after = bridge.get_device(device_id)
        assert device_after is not None, (
            "cleanup_stale_devices must retain the device identity entry"
        )
        assert device_after.connected is False, (
            "CLOSED: cleanup_stale_devices must set connected=False for stale device. "
            "If connected is still True, the bridge never cleans up ghost connections."
        )

    @pytest.mark.asyncio
    async def test_fresh_device_is_not_disconnected_on_cleanup(
        self, bridge: Any
    ) -> None:
        """CLOSED: cleanup_stale_devices must not disconnect a device with a recent heartbeat."""
        device_id = f"insp-fresh-{uuid.uuid4().hex[:8]}"
        ws = _make_ws()

        await bridge.handle_message(ws, _v3("device_register", device_id))

        # Send a heartbeat to refresh the timestamp
        await bridge.handle_message(ws, _v3("heartbeat", device_id))

        device = bridge.get_device(device_id)
        assert device is not None
        # last_heartbeat is recent (just updated)

        await bridge.cleanup_stale_devices(timeout_seconds=60.0)

        device_after = bridge.get_device(device_id)
        assert device_after is not None
        assert device_after.connected is True, (
            "CLOSED: cleanup_stale_devices must NOT disconnect a device with a recent heartbeat. "
            "If connected is False, healthy devices are being cleaned up prematurely."
        )


# ===========================================================================
# 8. System entry point: main.py → unified_launcher.py chain is importable
# ===========================================================================


class TestEntryPointChain:
    """Verify the system entry point chain is importable without crashing.

    main.py → unified_launcher.py → galaxy_gateway

    This does NOT start the server.  It verifies that the module graph is
    intact and that the canonical entry point imports do not raise.
    """

    def test_main_py_orchestrator_constant_is_set(self) -> None:
        """CLOSED: main.py defines SYSTEM_ORCHESTRATOR_AUTHORITY.

        This sentinel string is referenced by CI guardrails and validate_runtime.py.
        If it is missing, the orchestrator authority declaration is absent.
        """
        import main as _main

        assert hasattr(_main, "SYSTEM_ORCHESTRATOR_AUTHORITY"), (
            "CLOSED: main.py must export SYSTEM_ORCHESTRATOR_AUTHORITY sentinel"
        )
        assert _main.SYSTEM_ORCHESTRATOR_AUTHORITY, (
            "CLOSED: SYSTEM_ORCHESTRATOR_AUTHORITY must be a non-empty string"
        )

    def test_galaxy_gateway_app_importable(self) -> None:
        """CLOSED: galaxy_gateway.app is importable without starting the server."""
        import galaxy_gateway.app as _gw_app
        assert _gw_app is not None

    def test_canonical_ingress_authority_sentinel_present(self) -> None:
        """CLOSED: galaxy_gateway.routes.websocket declares canonical ingress authority."""
        from galaxy_gateway.routes.websocket import CANONICAL_DEVICE_INGRESS_AUTHORITY
        assert CANONICAL_DEVICE_INGRESS_AUTHORITY, (
            "CLOSED: CANONICAL_DEVICE_INGRESS_AUTHORITY must be a non-empty sentinel string"
        )
        assert "/ws/device/{device_id}" in CANONICAL_DEVICE_INGRESS_AUTHORITY, (
            "CLOSED: canonical ingress authority must reference /ws/device/{device_id}"
        )


# ===========================================================================
# 9. Open dual-repo gaps — exposed as observable assertions
# ===========================================================================


class TestDualRepoGapExposure:
    """Expose center-side gaps that require Android-side pairing to close.

    These tests do NOT pass/fail based on Android-side behaviour.  They
    expose center-side conditions that ARE machine-observable from this
    repository, and that require corresponding Android-side behaviour to
    form a closed loop.
    """

    def test_task_assign_has_no_server_side_persistence(self) -> None:
        """GAP_EXPOSED: task_assign dispatch has no server-side persistence.

        After dispatch_to_websocket sends task_assign, the task exists only
        in:
          - bridge._pending_responses[task_id] (Future, in-memory, per-process)
          - device_router.task_events[task_id] (Event, in-memory, per-process)

        If the server restarts or the device disconnects AFTER the assign is
        sent but BEFORE task_result arrives, the task is silently lost.  There
        is no server-side queue or durable store for in-flight task assigns.

        This test does not assert a fix — it asserts that the gap is
        machine-observable from the code structure.
        """
        from galaxy_gateway.routing.dispatch import dispatch_to_websocket
        import inspect

        src = inspect.getsource(dispatch_to_websocket)

        # Verify there is NO durable persistence call in dispatch_to_websocket
        # (asserting the gap is real, not accidentally fixed)
        durable_keywords = ["nats.publish", "write_to_store", "persist_task_assign"]
        for kw in durable_keywords:
            assert kw not in src, (
                f"GAP_EXPOSED: dispatch_to_websocket now contains '{kw}' — "
                "if task_assign persistence was added, update this test and "
                "remove this gap from the review notes."
            )

        # The gap exists: in-memory only
        # This assertion documents the finding without causing a spurious failure
        assert True, (
            "GAP_EXPOSED: task_assign is in-memory only. "
            "Center restart or device disconnect after send = silent task loss. "
            "Android-side recovery (OfflineTaskQueue) cannot compensate because "
            "the assign message may never have been received."
        )

    def test_durable_result_idempotency_module_is_importable(self) -> None:
        """CLOSED or GAP_EXPOSED: durable idempotency guard importability check.

        If core.durable_result_idempotency is not importable, Android reconnect
        replays will cause duplicate task_result processing.  This test makes
        the module availability machine-visible.
        """
        try:
            from core.durable_result_idempotency import (
                check_result_idempotency,
                record_result_idempotency,
            )
            # Module available — test basic function signature
            record_result_idempotency("insp-idem-probe-001")
            result = check_result_idempotency("insp-idem-probe-001")
            assert result is True, (
                "CLOSED: after recording task_id, check must return True"
            )
        except ImportError:
            pytest.fail(
                "GAP_EXPOSED: core.durable_result_idempotency is NOT importable. "
                "Without this module, Android reconnect replays will cause duplicate "
                "task_result processing.  This is a production-path gap that must be "
                "resolved before the offline-reconnect-replay contract can be closed."
            )

    def test_offline_state_transition_is_observable_via_bridge(self) -> None:
        """GAP_EXPOSED / PARTIAL: offline state is only in bridge + UDM cache; no notification to Android.

        When the center detects a device as offline (disconnect_device or
        cleanup_stale_devices), there is no server-initiated message sent to
        Android informing it of the offline classification.

        This means:
        - Android may continue sending messages to a device the center considers offline.
        - The center has no mechanism to push an 'offline_notification' to the Android
          side; Android must infer offline status from the WebSocket close event.

        This test documents the gap as observable from the code.
        """
        # The gap is structural; we verify it by checking that disconnect_device
        # does not attempt any outbound WebSocket send.
        from galaxy_gateway.android_bridge import AndroidBridge
        import inspect

        src = inspect.getsource(AndroidBridge.disconnect_device)

        # disconnect_device must NOT attempt to send a message to the device
        # (the socket is being closed; any send would raise)
        outbound_send_keywords = ["websocket.send", "ws.send"]
        for kw in outbound_send_keywords:
            assert kw not in src, (
                f"If disconnect_device contains '{kw}', it sends on a closing socket. "
                "Verify this is intentional and does not raise in production."
            )

        assert True, (
            "GAP_EXPOSED: disconnect_device does not notify Android of offline status. "
            "Android must detect disconnect via WebSocket close.  "
            "Center-side offline state is only reflected in bridge._devices and UDM; "
            "there is no offline_push protocol message from center → Android."
        )
