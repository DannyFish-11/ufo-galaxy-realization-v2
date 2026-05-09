"""
tests/integration/test_v2_android_protocol_regression.py
=========================================================
Protocol regression tests for the V2 ↔ Android interaction model.

This suite validates the critical non-happy-path behaviors that must remain
stable across cross-repo changes:

  1. Reconnect path — device reconnects after disconnect; V2 restores state
     correctly without creating duplicate identity.
  2. Offline queue / replay semantics — task_result messages that arrive after
     a task's Future has already been resolved are handled gracefully (no crash,
     no duplicate Future resolution).
  3. Duplicate result delivery — sending task_result twice for the same task_id
     must not raise an exception and must not attempt to set an already-done
     Future a second time.
  4. Handoff envelope reception — the V2 handoff signal path exists and is
     reachable code (not dead code).

All tests are self-contained and require no external services.

Design note: these tests target regression coverage of the protocol contract,
not performance or scalability.  They are meant to be run on every PR to
catch protocol drift between the V2 (Python) and Android (Kotlin) sides.
"""

import asyncio
import json
import time
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# AIP v3 message helper
# ---------------------------------------------------------------------------


def _v3(msg_type: str, device_id: str, **extra) -> Dict[str, Any]:
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


# ===========================================================================
# 1. Reconnect path regression
# ===========================================================================


class TestReconnectPath:
    """Device reconnects after disconnect; V2 state continuity is preserved."""

    @pytest.mark.asyncio
    async def test_reconnect_restores_connected_state(self) -> None:
        """After reconnect, device.connected must be True with the new websocket."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        device_id = f"reconnect-{uuid.uuid4().hex[:8]}"
        ws1 = _make_ws()
        ws2 = _make_ws()

        # Register via first connection
        await bridge.handle_message(
            ws1, _v3("device_register", device_id, platform="android")
        )

        device = bridge.get_device(device_id)
        assert device is not None
        assert device.connected is True

        # Simulate disconnect
        await bridge.disconnect_device(device_id)
        device = bridge.get_device(device_id)
        assert device is not None
        assert device.connected is False

        # Reconnect with a new websocket
        success = await bridge.reconnect_device(device_id, ws2)
        assert success is True

        device = bridge.get_device(device_id)
        assert device is not None
        assert device.connected is True
        assert device.websocket is ws2

    @pytest.mark.asyncio
    async def test_reconnect_unknown_device_returns_false(self) -> None:
        """reconnect_device must return False for a device that was never registered."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        ws = _make_ws()
        fake_id = f"unknown-{uuid.uuid4().hex[:8]}"

        result = await bridge.reconnect_device(fake_id, ws)
        assert result is False, (
            "reconnect_device must return False for unknown device_id"
        )

    @pytest.mark.asyncio
    async def test_reconnect_preserves_capability_state(self) -> None:
        """Capabilities reported before disconnect must still be present after reconnect."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        device_id = f"reconnect-cap-{uuid.uuid4().hex[:8]}"
        ws1 = _make_ws()
        ws2 = _make_ws()
        caps = ["tap", "swipe", "screenshot"]

        # Register + report capabilities
        await bridge.handle_message(
            ws1, _v3("device_register", device_id, platform="android")
        )
        await bridge.handle_message(
            ws1,
            _v3("capability_report", device_id, platform="android", supported_actions=caps),
        )

        device = bridge.get_device(device_id)
        assert device is not None
        for cap in caps:
            assert cap in device.supported_actions

        # Disconnect + reconnect
        await bridge.disconnect_device(device_id)
        await bridge.reconnect_device(device_id, ws2)

        # Capabilities must survive the reconnect cycle
        device = bridge.get_device(device_id)
        assert device is not None
        for cap in caps:
            assert cap in device.supported_actions, (
                f"Capability '{cap}' lost after reconnect — capability state regression"
            )

    @pytest.mark.asyncio
    async def test_reconnect_new_registration_replaces_old(self) -> None:
        """A second device_register from the same device_id is accepted.

        Android clients may re-register if they restart.  V2 must accept the
        re-registration and update device state without error.
        """
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        device_id = f"rereg-{uuid.uuid4().hex[:8]}"
        ws1 = _make_ws()
        ws2 = _make_ws()

        # First registration
        reg1 = await bridge.handle_message(
            ws1, _v3("device_register", device_id, platform="android", model="Phone v1")
        )
        assert reg1["type"] == "device_register_ack"

        # Second registration (client restart / reconnect via register)
        reg2 = await bridge.handle_message(
            ws2, _v3("device_register", device_id, platform="android", model="Phone v1")
        )
        assert reg2 is not None
        assert reg2["type"] == "device_register_ack", (
            "Re-registration must be accepted — V2 must not reject a second "
            "device_register for the same device_id"
        )

    def test_reconnect_via_transport_layer(self) -> None:
        """Reconnect path through the real WS transport (FastAPI TestClient).

        Simulates a device that disconnects and reconnects on the canonical
        ``/ws/device/{device_id}`` path.  V2 must correctly accept both
        connections and route messages after reconnect.
        """
        from fastapi import FastAPI, WebSocket
        from fastapi.testclient import TestClient

        from galaxy_gateway.routes.websocket import _handle_android_ws

        app = FastAPI()

        @app.websocket("/ws/device/{device_id}")
        async def ws(websocket: WebSocket, device_id: str) -> None:
            await _handle_android_ws(websocket, device_id)

        device_id = f"reconnect-ws-{uuid.uuid4().hex[:8]}"

        with TestClient(app) as client:
            # First connection: register
            with client.websocket_connect(f"/ws/device/{device_id}") as ws1:
                ws1.send_text(
                    json.dumps(_v3("device_register", device_id, platform="android"))
                )
                ack1 = ws1.receive_json()
            assert ack1["type"] == "device_register_ack"

            # Second connection (reconnect): register again
            with client.websocket_connect(f"/ws/device/{device_id}") as ws2:
                ws2.send_text(
                    json.dumps(_v3("device_register", device_id, platform="android"))
                )
                ack2 = ws2.receive_json()
            assert ack2["type"] == "device_register_ack", (
                "Reconnect registration must succeed — V2 must handle device "
                "reconnects via new WS connections"
            )


# ===========================================================================
# 2. Offline queue / replay semantics
# ===========================================================================


class TestOfflineQueueReplaySemantics:
    """task_result for unknown / already-resolved task_ids is handled gracefully."""

    @pytest.mark.asyncio
    async def test_task_result_for_unknown_task_id_no_crash(self) -> None:
        """task_result with no matching Future must not crash V2.

        This is the "replay" scenario: Android sends a result for a task that
        V2 has no pending waiter for (e.g. because V2 restarted or the task
        was already cancelled).  V2 must process it gracefully.
        """
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        device_id = f"replay-{uuid.uuid4().hex[:8]}"
        ws = _make_ws()
        unknown_task_id = f"no-waiter-{uuid.uuid4().hex[:8]}"

        await bridge.handle_message(
            ws, _v3("device_register", device_id, platform="android")
        )

        # task_result with no matching pending Future — must not raise
        response = await bridge.handle_message(
            ws,
            _v3(
                "task_result",
                device_id,
                task_id=unknown_task_id,
                status="completed",
                result={"data": "replayed"},
            ),
        )
        # handle_task_result returns None; None is an acceptable response here
        assert response is None or isinstance(response, dict)

    @pytest.mark.asyncio
    async def test_multiple_task_results_without_matching_futures_no_crash(
        self,
    ) -> None:
        """Multiple replayed results must not crash V2.

        Simulates an Android client that sends several results on reconnect
        (offline queue drain).  V2 must process each without raising.
        """
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        device_id = f"multi-replay-{uuid.uuid4().hex[:8]}"
        ws = _make_ws()

        await bridge.handle_message(
            ws, _v3("device_register", device_id, platform="android")
        )

        for i in range(5):
            task_id = f"queued-task-{i}-{uuid.uuid4().hex[:6]}"
            await bridge.handle_message(
                ws,
                _v3(
                    "task_result",
                    device_id,
                    task_id=task_id,
                    status="completed",
                    result={"index": i},
                ),
            )
        # If we reach here without exception, the replay path is safe

    @pytest.mark.asyncio
    async def test_task_result_after_disconnect_reconnect_no_crash(self) -> None:
        """task_result can arrive after disconnect; V2 must not crash."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        device_id = f"offline-result-{uuid.uuid4().hex[:8]}"
        ws1 = _make_ws()
        ws2 = _make_ws()
        task_id = str(uuid.uuid4())

        # Register on first connection and set up a pending future
        await bridge.handle_message(
            ws1, _v3("device_register", device_id, platform="android")
        )
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        bridge._pending_responses[task_id] = future

        # Disconnect
        await bridge.disconnect_device(device_id)

        # Reconnect
        await bridge.reconnect_device(device_id, ws2)

        # task_result arrives after reconnect — future must still be resolved
        await bridge.handle_message(
            ws2,
            _v3(
                "task_result",
                device_id,
                task_id=task_id,
                status="completed",
                result={"data": "late_result"},
            ),
        )

        assert future.done(), (
            "Future must be resolved even when task_result arrives after reconnect"
        )


# ===========================================================================
# 3. Duplicate result delivery
# ===========================================================================


class TestDuplicateResultDelivery:
    """Sending task_result twice for the same task_id must be idempotent."""

    @pytest.mark.asyncio
    async def test_duplicate_task_result_no_exception(self) -> None:
        """A second task_result for the same task_id must not raise an exception.

        Android may send duplicate results due to retry logic or network issues.
        V2 must handle this idempotently — the second delivery must be a no-op.
        """
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        device_id = f"dup-{uuid.uuid4().hex[:8]}"
        task_id = str(uuid.uuid4())
        ws = _make_ws()

        await bridge.handle_message(
            ws, _v3("device_register", device_id, platform="android")
        )

        # Install Future
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        bridge._pending_responses[task_id] = future

        # First delivery — resolves the Future
        await bridge.handle_message(
            ws,
            _v3("task_result", device_id, task_id=task_id, status="completed"),
        )
        assert future.done()

        # Second delivery — no matching Future; must not raise
        await bridge.handle_message(
            ws,
            _v3("task_result", device_id, task_id=task_id, status="completed"),
        )
        # If we reach here, duplicate delivery was handled gracefully

    @pytest.mark.asyncio
    async def test_duplicate_task_result_does_not_double_resolve_future(
        self,
    ) -> None:
        """A second task_result must not attempt to set an already-resolved Future."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        device_id = f"dup-future-{uuid.uuid4().hex[:8]}"
        task_id = str(uuid.uuid4())
        ws = _make_ws()

        await bridge.handle_message(
            ws, _v3("device_register", device_id, platform="android")
        )

        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        bridge._pending_responses[task_id] = future

        result_msg = _v3("task_result", device_id, task_id=task_id, status="completed")

        # First delivery
        await bridge.handle_message(ws, result_msg)
        first_result = future.result()
        assert future.done()

        # Second delivery — Future is already gone from _pending_responses;
        # must not raise InvalidStateError
        await bridge.handle_message(ws, result_msg)

        # First result must be unchanged
        assert future.result() == first_result, (
            "Future result must not be overwritten by duplicate task_result"
        )

    @pytest.mark.asyncio
    async def test_different_task_ids_handled_independently(self) -> None:
        """task_results for different task_ids must resolve their respective Futures."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        device_id = f"multi-task-{uuid.uuid4().hex[:8]}"
        ws = _make_ws()

        await bridge.handle_message(
            ws, _v3("device_register", device_id, platform="android")
        )

        loop = asyncio.get_event_loop()
        task_id_a = str(uuid.uuid4())
        task_id_b = str(uuid.uuid4())
        future_a: asyncio.Future = loop.create_future()
        future_b: asyncio.Future = loop.create_future()
        bridge._pending_responses[task_id_a] = future_a
        bridge._pending_responses[task_id_b] = future_b

        # Deliver result for B first, then A
        await bridge.handle_message(
            ws,
            _v3("task_result", device_id, task_id=task_id_b, status="completed",
                result={"which": "B"},
                ),
        )
        await bridge.handle_message(
            ws,
            _v3("task_result", device_id, task_id=task_id_a, status="completed",
                result={"which": "A"},
                ),
        )

        assert future_a.done(), "Future for task_id_a must be resolved"
        assert future_b.done(), "Future for task_id_b must be resolved"


# ===========================================================================
# 4. Handoff envelope reception path
# ===========================================================================


class TestHandoffSignalPath:
    """Handoff envelope reception path must be reachable (not dead code)."""

    @pytest.mark.asyncio
    async def test_handoff_related_message_type_does_not_crash(self) -> None:
        """An unrecognised or handoff-style message type must not crash the bridge.

        V2 must tolerate unknown message types gracefully — returning an error
        response or None, but never raising an unhandled exception.
        This guards against the handoff ingress path becoming silently dead.
        """
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        device_id = f"handoff-{uuid.uuid4().hex[:8]}"
        ws = _make_ws()

        await bridge.handle_message(
            ws, _v3("device_register", device_id, platform="android")
        )

        # Send a handoff-style envelope (unrecognised type)
        result = await bridge.handle_message(
            ws,
            _v3(
                "session_handoff",
                device_id,
                payload={"continuation_token": "abc", "session_id": "sess-001"},
            ),
        )
        # Must not raise; may return error dict or None
        assert result is None or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_task_end_handler_reachable(self) -> None:
        """task_end handler must be reachable and return a structured ack."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        device_id = f"task-end-{uuid.uuid4().hex[:8]}"
        task_id = str(uuid.uuid4())
        ws = _make_ws()

        await bridge.handle_message(
            ws, _v3("device_register", device_id, platform="android")
        )

        ack = await bridge.handle_message(
            ws,
            _v3(
                "task_end",
                device_id,
                task_id=task_id,
                status="completed",
            ),
        )
        # task_end handler must produce a task_end_ack
        assert ack is not None, "task_end must return a response (not dead code)"
        assert ack.get("type") == "task_end_ack", (
            f"Expected 'task_end_ack', got {ack.get('type')!r}"
        )

    @pytest.mark.asyncio
    async def test_goal_result_ingress_path_exists(self) -> None:
        """goal_result ingress handler must be reachable without crashing.

        goal_result is a cross-repo contract type used by higher-level Android
        orchestration flows.  If it arrives, V2 must not crash.
        """
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        device_id = f"goal-result-{uuid.uuid4().hex[:8]}"
        ws = _make_ws()

        await bridge.handle_message(
            ws, _v3("device_register", device_id, platform="android")
        )

        result = await bridge.handle_message(
            ws,
            _v3(
                "goal_result",
                device_id,
                task_id=str(uuid.uuid4()),
                status="completed",
                result={"goal": "done"},
            ),
        )
        # Must not raise; response type varies by handler implementation
        assert result is None or isinstance(result, dict)

    def test_handle_task_result_function_is_not_dead_code(self) -> None:
        """handle_task_result must be importable and callable."""
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_result

        assert callable(handle_task_result), (
            "handle_task_result must be a callable — handoff waiter resolution "
            "path must not be dead code"
        )

    def test_reconnect_device_method_exists_and_is_callable(self) -> None:
        """reconnect_device must exist on AndroidBridge as a callable method."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        assert callable(bridge.reconnect_device), (
            "AndroidBridge.reconnect_device must be callable — reconnect path "
            "must not be dead code"
        )

    def test_dispatch_to_websocket_function_is_importable(self) -> None:
        """dispatch_to_websocket must be importable from the routing module."""
        from galaxy_gateway.routing.dispatch import dispatch_to_websocket

        assert callable(dispatch_to_websocket), (
            "dispatch_to_websocket must be importable and callable — "
            "V2→Android command dispatch path must not be dead code"
        )


# ===========================================================================
# 5. Session identity continuity
# ===========================================================================


class TestSessionIdentityContinuity:
    """Session identity (device_id) must be stable across protocol operations."""

    @pytest.mark.asyncio
    async def test_device_id_consistent_across_register_and_capability(self) -> None:
        """device_id in register_ack and capability_report_ack must match."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        device_id = f"session-id-{uuid.uuid4().hex[:8]}"
        ws = _make_ws()

        reg_ack = await bridge.handle_message(
            ws, _v3("device_register", device_id, platform="android")
        )
        cap_ack = await bridge.handle_message(
            ws,
            _v3(
                "capability_report",
                device_id,
                platform="android",
                supported_actions=["tap"],
            ),
        )

        assert reg_ack["device_id"] == device_id
        assert cap_ack["device_id"] == device_id

    @pytest.mark.asyncio
    async def test_multiple_devices_independent_state(self) -> None:
        """Two concurrent devices must have independent, non-overlapping state."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        device_a = f"dev-a-{uuid.uuid4().hex[:8]}"
        device_b = f"dev-b-{uuid.uuid4().hex[:8]}"
        ws_a = _make_ws()
        ws_b = _make_ws()
        caps_a = ["tap", "swipe"]
        caps_b = ["screenshot", "input_text"]

        # Register and report capabilities for both devices
        await bridge.handle_message(
            ws_a, _v3("device_register", device_a, platform="android")
        )
        await bridge.handle_message(
            ws_b, _v3("device_register", device_b, platform="android")
        )
        await bridge.handle_message(
            ws_a,
            _v3("capability_report", device_a, platform="android", supported_actions=caps_a),
        )
        await bridge.handle_message(
            ws_b,
            _v3("capability_report", device_b, platform="android", supported_actions=caps_b),
        )

        dev_a_obj = bridge.get_device(device_a)
        dev_b_obj = bridge.get_device(device_b)

        assert dev_a_obj is not None
        assert dev_b_obj is not None
        assert dev_a_obj is not dev_b_obj

        for cap in caps_a:
            assert cap in dev_a_obj.supported_actions
        for cap in caps_b:
            assert cap in dev_b_obj.supported_actions
        # No cross-contamination
        for cap in caps_b:
            assert cap not in dev_a_obj.supported_actions, (
                f"Device A must not have device B's capability '{cap}'"
            )


# ===========================================================================
# 6. Reconnect continuity semantics
# ===========================================================================


class TestReconnectContinuitySemantics:
    """Re-register + continuity fields must be recognised as the same session.

    These tests validate the canonical Android reconnect path:
      - Android client reconnects by sending ``device_register`` with the same
        ``runtime_attachment_session_id`` that was echoed in the previous ack.
      - The server responds with ``continuity_outcome = "continuity_resume"`` and
        preserves the stable ``runtime_session_id``.
      - A re-registration with a *different* (or absent first-time) attachment ID
        is classified as ``"new_attachment"`` — a fresh session.
      - The explicit ``device_reconnect`` wire message is NOT the canonical path
        and must not be required for reconnect continuity to work.
    """

    @pytest.mark.asyncio
    async def test_reregister_with_same_attachment_id_is_continuity_resume(
        self,
    ) -> None:
        """Re-registration with the same runtime_attachment_session_id → continuity_resume.

        Android production reconnect: new WebSocket + device_register with same
        runtime_attachment_session_id.  The server must detect this as a continuity
        resume and preserve the runtime_session_id.
        """
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        device_id = f"continuity-{uuid.uuid4().hex[:8]}"
        attachment_id = str(uuid.uuid4())
        ws1 = _make_ws()
        ws2 = _make_ws()

        # First registration — establishes session
        ack1 = await bridge.handle_message(
            ws1,
            _v3(
                "device_register",
                device_id,
                platform="android",
                runtime_attachment_session_id=attachment_id,
            ),
        )
        assert ack1["type"] == "device_register_ack"
        assert ack1["runtime_attachment_session_id"] == attachment_id
        # First registration is always a new attachment (no prior session)
        assert ack1.get("continuity_outcome") in ("new_attachment", None), (
            "First registration must be new_attachment or unclassified"
        )

        # Simulate disconnect so the session is in detached state
        await bridge.disconnect_device(device_id)

        # Reconnect via re-registration with the SAME attachment id
        ack2 = await bridge.handle_message(
            ws2,
            _v3(
                "device_register",
                device_id,
                platform="android",
                runtime_attachment_session_id=attachment_id,
            ),
        )
        assert ack2["type"] == "device_register_ack"
        assert ack2.get("continuity_outcome") == "continuity_resume", (
            "Re-registration with the same runtime_attachment_session_id must be "
            "classified as continuity_resume — this is the canonical Android reconnect path"
        )
        # runtime_attachment_session_id must be echoed back
        assert ack2["runtime_attachment_session_id"] == attachment_id

    @pytest.mark.asyncio
    async def test_reregister_with_different_attachment_id_is_new_attachment(
        self,
    ) -> None:
        """Re-registration with a different attachment ID → new_attachment (not continuity)."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        device_id = f"newattach-{uuid.uuid4().hex[:8]}"
        attachment_id_1 = str(uuid.uuid4())
        attachment_id_2 = str(uuid.uuid4())
        ws1 = _make_ws()
        ws2 = _make_ws()

        # First registration
        ack1 = await bridge.handle_message(
            ws1,
            _v3(
                "device_register",
                device_id,
                platform="android",
                runtime_attachment_session_id=attachment_id_1,
            ),
        )
        assert ack1["type"] == "device_register_ack"

        await bridge.disconnect_device(device_id)

        # Second registration with a DIFFERENT attachment id (e.g. app reinstall)
        ack2 = await bridge.handle_message(
            ws2,
            _v3(
                "device_register",
                device_id,
                platform="android",
                runtime_attachment_session_id=attachment_id_2,
            ),
        )
        assert ack2["type"] == "device_register_ack"
        assert ack2.get("continuity_outcome") == "new_attachment", (
            "Re-registration with a different runtime_attachment_session_id must be "
            "classified as new_attachment — prevents session ID spoofing and "
            "correctly represents a fresh connection"
        )

    @pytest.mark.asyncio
    async def test_continuity_resume_preserves_runtime_session_id(self) -> None:
        """Continuity resume must preserve the stable runtime_session_id.

        When Android reconnects with the same attachment ID, the server must call
        reconnect_session() (not register_session()), preserving runtime_session_id.
        """
        from core.attached_runtime_session_registry import (
            get_session_registry,
        )
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        device_id = f"session-persist-{uuid.uuid4().hex[:8]}"
        attachment_id = str(uuid.uuid4())
        ws1 = _make_ws()
        ws2 = _make_ws()
        registry = get_session_registry()

        # First registration
        ack = await bridge.handle_message(
            ws1,
            _v3(
                "device_register",
                device_id,
                platform="android",
                runtime_attachment_session_id=attachment_id,
            ),
        )
        assert isinstance(ack, dict)
        runtime_session_id_before = ack.get("runtime_session_id")
        assert runtime_session_id_before, (
            "Expected runtime_session_id in device_register_ack but got None"
        )
        # Capture the runtime_session_id after first registration
        entry1 = registry.get_active_for_device(device_id)
        assert entry1 is not None, "Registry must have an entry after registration"
        assert entry1.runtime_session_id == runtime_session_id_before

        # Disconnect
        await bridge.disconnect_device(device_id)

        # Reconnect via re-registration with same attachment id
        ack2 = await bridge.handle_message(
            ws2,
            _v3(
                "device_register",
                device_id,
                platform="android",
                runtime_attachment_session_id=attachment_id,
            ),
        )
        assert ack2["runtime_session_id"] == runtime_session_id_before
        assert ack2["continuity_outcome"] == "continuity_resume"
        entry2 = registry.get_active_for_device(device_id)
        assert entry2 is not None, "Registry must have an active entry after reconnect"
        assert entry2.runtime_session_id == runtime_session_id_before, (
            "Continuity resume must preserve the runtime_session_id — "
            "reconnect_session() must be used instead of register_session()"
        )

    @pytest.mark.asyncio
    async def test_canonical_reregister_replays_buffered_messages(self) -> None:
        """Canonical reconnect must replay buffered task dispatches on continuity resume."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from galaxy_gateway.pending_delivery_buffer import pending_delivery_buffer

        bridge = AndroidBridge()
        device_id = f"replay-resume-{uuid.uuid4().hex[:8]}"
        attachment_id = str(uuid.uuid4())
        task_id = f"buffered-{uuid.uuid4().hex[:8]}"
        ws1 = _make_ws()
        ws2 = _make_ws()

        await pending_delivery_buffer.discard_device(device_id)

        ack1 = await bridge.handle_message(
            ws1,
            _v3(
                "device_register",
                device_id,
                platform="android",
                runtime_attachment_session_id=attachment_id,
            ),
        )
        assert ack1["recovery_replay_scheduled"] is False
        assert ack1["recovery_replay_buffered_count"] == 0
        assert ack1["runtime_session_id"]

        await bridge.disconnect_device(device_id)

        buffered = await bridge.send_to_device(
            device_id,
            {
                "version": "3.0",
                "type": "task_assign",
                "message_id": str(uuid.uuid4()),
                "device_id": device_id,
                "task_id": task_id,
                "timestamp": int(time.time() * 1000),
                "payload": {"task_type": "resume_task", "step": "replay"},
            },
        )
        assert buffered is not None
        assert buffered.get("buffered") is True
        assert pending_delivery_buffer.queue_size(device_id) == 1

        ack2 = await bridge.handle_message(
            ws2,
            _v3(
                "device_register",
                device_id,
                platform="android",
                runtime_attachment_session_id=attachment_id,
            ),
        )
        assert ack2["continuity_outcome"] == "continuity_resume"
        assert ack2["recovery_replay_scheduled"] is True
        assert ack2["recovery_replay_buffered_count"] == 1

        await asyncio.sleep(0.01)

        ws2.send_json.assert_awaited_once()
        replayed = ws2.send_json.await_args_list[0].args[0]
        assert replayed["type"] == "task_assign"
        assert replayed["task_id"] == task_id
        assert pending_delivery_buffer.queue_size(device_id) == 0
        await pending_delivery_buffer.discard_device(device_id)

    @pytest.mark.asyncio
    async def test_disconnect_reconnect_restores_context_and_converges_result(self) -> None:
        """Reconnect path must preserve context, resume tracking, and converge the final result."""
        from core.android_participant_session_state import (
            AndroidParticipantSessionPhase,
            get_participant_session,
        )
        from core.android_delegated_runtime_lifecycle_coordinator import (
            get_lifecycle_coordinator,
        )
        from core.delegated_runtime_execution_tracker import (
            DelegatedExecutionPhase,
            create_execution_tracking_record,
            get_active_execution_tracking_for_session,
            get_execution_tracking_record,
            reset_execution_tracking_runtime,
        )
        from core.takeover_tracking import (
            get_takeover_record,
            reset_takeover_tracking_runtime,
        )
        from galaxy_gateway.android_bridge import AndroidBridge

        reset_execution_tracking_runtime()
        reset_takeover_tracking_runtime()

        bridge = AndroidBridge()
        device_id = f"resume-proof-{uuid.uuid4().hex[:8]}"
        attachment_id = str(uuid.uuid4())
        contract_id = f"contract-{uuid.uuid4().hex[:8]}"
        task_id = f"task-{uuid.uuid4().hex[:8]}"
        trace_id = f"trace-{uuid.uuid4().hex[:8]}"
        takeover_id = f"takeover-{uuid.uuid4().hex[:8]}"
        ws1 = _make_ws()
        ws2 = _make_ws()

        ack1 = await bridge.handle_message(
            ws1,
            _v3(
                "device_register",
                device_id,
                platform="android",
                runtime_attachment_session_id=attachment_id,
            ),
        )
        runtime_session_id = ack1["runtime_session_id"]

        create_execution_tracking_record(
            session_id=runtime_session_id,
            contract_id=contract_id,
            device_id=device_id,
            trace_id=trace_id,
            source_runtime_posture="join_runtime",
        )
        coordinator = get_lifecycle_coordinator()
        coordinator.on_handoff_dispatched(
            session_id=runtime_session_id,
            device_id=device_id,
            task_id=task_id,
            trace_id=trace_id,
            contract_id=contract_id,
        )
        coordinator.on_takeover_requested(
            session_id=runtime_session_id,
            takeover_id=takeover_id,
            device_id=device_id,
            task_id=task_id,
            trace_id=trace_id,
        )
        takeover_pending = get_participant_session(runtime_session_id)
        assert takeover_pending is not None
        assert takeover_pending.phase == AndroidParticipantSessionPhase.takeover_pending

        future = asyncio.get_running_loop().create_future()
        bridge._pending_responses[task_id] = future

        await bridge.disconnect_device(device_id)

        ack2 = await bridge.handle_message(
            ws2,
            _v3(
                "device_register",
                device_id,
                platform="android",
                runtime_attachment_session_id=attachment_id,
            ),
        )
        assert ack2["continuity_outcome"] == "continuity_resume"
        assert ack2["runtime_session_id"] == runtime_session_id

        active = get_active_execution_tracking_for_session(runtime_session_id)
        assert active is not None
        assert active.phase == DelegatedExecutionPhase.pending_ack

        takeover_ack = await bridge.handle_message(
            ws2,
            _v3(
                "takeover_response",
                device_id,
                takeover_id=takeover_id,
                accepted=True,
                reason="resume_after_reconnect",
                task_id=task_id,
                trace_id=trace_id,
            ),
        )
        assert takeover_ack["type"] == "takeover_response_ack"
        resumed_takeover = get_participant_session(runtime_session_id)
        assert resumed_takeover is not None
        assert resumed_takeover.phase == AndroidParticipantSessionPhase.takeover_accepted
        takeover_record = get_takeover_record(takeover_id)
        assert takeover_record is not None
        assert takeover_record.session_id == runtime_session_id
        assert takeover_record.decision.value == "accepted"

        continuity_payload = {
            "contract_id": contract_id,
            "session_id": runtime_session_id,
            "trace_id": trace_id,
            "result": {"value": "final"},
        }

        await bridge.handle_message(
            ws2,
            _v3(
                "task_progress",
                device_id,
                task_id=task_id,
                contract_id=contract_id,
                session_id=runtime_session_id,
                trace_id=trace_id,
                status="running",
                progress=55,
                payload=continuity_payload,
            ),
        )

        progressed = get_execution_tracking_record(runtime_session_id)
        assert progressed is not None
        assert progressed.phase == DelegatedExecutionPhase.in_progress

        await bridge.handle_message(
            ws2,
            _v3(
                "task_result",
                device_id,
                task_id=task_id,
                contract_id=contract_id,
                session_id=runtime_session_id,
                trace_id=trace_id,
                status="completed",
                payload=continuity_payload,
            ),
        )

        assert future.result()["payload"]["result"]["value"] == "final"

        completed = get_execution_tracking_record(runtime_session_id)
        assert completed is not None
        assert completed.phase == DelegatedExecutionPhase.completed
        assert completed.result is not None
        assert completed.result.result_payload["value"] == "final"

    def test_device_reconnect_message_is_not_canonical_path_sentinel(self) -> None:
        """The codebase sentinel must affirm that device_reconnect is NOT the canonical path."""
        from galaxy_gateway.android.handlers.registration import (
            DEVICE_REGISTER_IS_CANONICAL_RECONNECT_PATH,
        )
        from galaxy_gateway.android_bridge import (
            ANDROID_RECONNECT_CANONICAL_PATH_SENTINEL,
        )

        assert "device_register" in DEVICE_REGISTER_IS_CANONICAL_RECONNECT_PATH
        assert "NOT" in ANDROID_RECONNECT_CANONICAL_PATH_SENTINEL, (
            "Sentinel must explicitly state that device_reconnect is NOT the canonical path"
        )

    @pytest.mark.asyncio
    async def test_reregister_without_attachment_id_falls_back_gracefully(
        self,
    ) -> None:
        """Re-registration without attachment ID must be accepted (backward compat).

        Android clients that do not supply runtime_attachment_session_id must
        still be able to reconnect without error.
        """
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        device_id = f"noattach-{uuid.uuid4().hex[:8]}"
        ws1 = _make_ws()
        ws2 = _make_ws()

        # First registration — no explicit attachment id
        ack1 = await bridge.handle_message(
            ws1,
            _v3("device_register", device_id, platform="android"),
        )
        assert ack1["type"] == "device_register_ack"

        # Second registration — no explicit attachment id
        ack2 = await bridge.handle_message(
            ws2,
            _v3("device_register", device_id, platform="android"),
        )
        assert ack2 is not None
        assert ack2["type"] == "device_register_ack", (
            "Re-registration without attachment ID must succeed — backward compat"
        )
        # continuity_outcome must be present and must be one of the two valid values
        assert ack2.get("continuity_outcome") in ("continuity_resume", "new_attachment"), (
            "continuity_outcome must always be present in device_register_ack"
        )
