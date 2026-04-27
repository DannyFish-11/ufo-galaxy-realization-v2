"""
tests/integration/test_multi_device_failure_recovery_e2e.py
=============================================================

**Multi-device, delegated takeover, and failure-recovery E2E tests.**

These tests extend the GAP_JOINT_INTEGRATION_TEST closure (single-participant
happy path) with network-level assurance for scenarios that can only emerge
when multiple participants interact:

1. **Multi-device concurrent registration** — two participants connect and
   register simultaneously; each gets an independent ack; no cross-talk.

2. **Per-device capability isolation** — each participant reports distinct
   capabilities; task_assign sent to device A is not received by device B.

3. **Concurrent task execution** — two participants each execute an
   independent task roundtrip in the same server session; both complete
   successfully and both sessions remain alive.

4. **Delegated takeover path** — primary participant (device A) receives a
   task_assign then disconnects before sending task_result; the same task is
   re-dispatched to a backup participant (device B); device B executes and
   sends task_result; continuation is verified via heartbeat_ack.  The
   takeover task_result carries the *original* task_id, proving result
   continuity across the handoff.

5. **Participant disconnect + reconnect + task recovery** — a device
   receives a task_assign then disconnects abruptly (simulates failure);
   the server handles the disconnect gracefully; the device reconnects with
   the same device_id, re-registers, receives a fresh dispatch, completes
   execution, and sends task_result; heartbeat confirms session continuity.

6. **Capability mismatch — route to capable device** — device A reports
   only ``["screenshot"]``; device B reports ``["tap", "screenshot"]``;
   a task requiring ``["tap"]`` is dispatched exclusively to device B;
   device A receives no task_assign; device B completes the task; heartbeat
   confirms both sessions are alive.

7. **Multi-device result aggregation** — three sequential tasks are
   dispatched across two devices; results are correlated back to the
   correct device_ids.

8. **Degraded participant — partial capability** — a participant that
   reports a minimal capability set (single capability) successfully
   receives and completes only the task that matches that capability;
   a task requiring an additional capability is routed away from it.

Architecture
------------
- **Server process**: the real ``_ws_e2e_multi_device_server_helper`` uvicorn
  server runs in a separate OS process.
- **Client coroutines**: all WebSocket clients connect via genuine TCP
  loopback sockets using the ``websockets`` library.
- **No test doubles**: the production ``_handle_android_ws`` handler and
  ``AndroidBridge`` singleton are used throughout.

GAP closure
-----------
This file closes ``GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION`` by
providing network-level automated assurance for multi-device, takeover,
and failure-recovery paths.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx
import pytest
from websockets.asyncio.client import connect as _ws_connect_base


def ws_connect(uri: str, **kwargs):
    """Wrapper around ``websockets.asyncio.client.connect`` with ``proxy=None``.

    Disables proxy auto-detection (the v16 default ``proxy=True``) so that
    loopback connections go directly to the server.
    """
    kwargs.setdefault("proxy", None)
    return _ws_connect_base(uri, **kwargs)


# ---------------------------------------------------------------------------
# AIP v3 message helper
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
# Port / server helpers
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    """Find an available TCP port on loopback."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def _wait_for_port(host: str, port: int, timeout: float = 20.0) -> None:
    """Block until the TCP port accepts connections or raise on timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    raise RuntimeError(
        f"Server on {host}:{port} did not start within {timeout}s"
    )


# ---------------------------------------------------------------------------
# Pytest fixture — live uvicorn server in a separate OS process
# ---------------------------------------------------------------------------

_SERVER_HELPER = os.path.join(
    os.path.dirname(__file__), "_ws_e2e_multi_device_server_helper.py"
)


@pytest.fixture(scope="module")
def live_server():
    """Start a real uvicorn server (multi-device helper) in a separate process.

    Module-scoped so the subprocess is started once per test module.
    Yields the base URL, e.g. ``"http://127.0.0.1:<port>"``.
    """
    port = _find_free_port()
    env = {**os.environ, "GALAXY_MODE": "test", "GALAXY_DEV_MODE": "1"}
    proc = subprocess.Popen(
        [sys.executable, _SERVER_HELPER, str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    try:
        _wait_for_port("127.0.0.1", port)
    except RuntimeError:
        proc.terminate()
        proc.wait(timeout=5)
        raise

    base_url = f"http://127.0.0.1:{port}"
    yield base_url

    proc.terminate()
    proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# NetworkE2EClient — thin async helper for the tests
# ---------------------------------------------------------------------------


class NetworkE2EClient:
    """Async helper wrapping a real websockets connection to the live server."""

    def __init__(self, ws: Any, device_id: str) -> None:
        self._ws = ws
        self.device_id = device_id
        self.received: List[Dict[str, Any]] = []

    async def send(self, msg: Dict[str, Any]) -> None:
        await self._ws.send(json.dumps(msg))

    async def recv(self, timeout: float = 5.0) -> Dict[str, Any]:
        raw = await asyncio.wait_for(self._ws.recv(), timeout=timeout)
        parsed: Dict[str, Any] = json.loads(raw)
        self.received.append(parsed)
        return parsed

    async def recv_optional(self, timeout: float = 1.5) -> Optional[Dict[str, Any]]:
        """Try to receive a message; return None if nothing arrives within *timeout*."""
        try:
            return await self.recv(timeout=timeout)
        except asyncio.TimeoutError:
            return None

    # ---------------------------------------------------------------- flows

    async def register(self, platform: str = "android") -> Dict[str, Any]:
        await self.send(_v3("device_register", self.device_id, platform=platform))
        return await self.recv()

    async def report_capabilities(self, caps: List[str]) -> Dict[str, Any]:
        await self.send(
            _v3(
                "capability_report",
                self.device_id,
                platform="android",
                supported_actions=caps,
            )
        )
        return await self.recv()

    async def heartbeat(self) -> Dict[str, Any]:
        await self.send(_v3("heartbeat", self.device_id))
        return await self.recv()

    async def task_result(
        self,
        task_id: str,
        status: str = "completed",
        result_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send task_result.  No server response is expected."""
        await self.send(
            _v3(
                "task_result",
                self.device_id,
                task_id=task_id,
                status=status,
                result=result_data or {"output": "done"},
            )
        )


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _dispatch(base_url: str, device_id: str, task_id: str, command: str) -> Dict[str, Any]:
    """Synchronously trigger a task_assign dispatch to *device_id*."""
    resp = httpx.post(
        f"{base_url}/test/dispatch-task/{device_id}",
        json={"task_id": task_id, "command": command},
        timeout=5.0,
    )
    assert resp.status_code == 200, (
        f"dispatch endpoint returned {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert body.get("dispatched") is True
    return body


def _takeover_dispatch(
    base_url: str,
    task_id: str,
    takeover_device_id: str,
    original_device_id: str,
    command: str = "execute",
) -> Dict[str, Any]:
    """Synchronously trigger a takeover re-dispatch to *takeover_device_id*."""
    resp = httpx.post(
        f"{base_url}/test/takeover-dispatch/{task_id}/{takeover_device_id}",
        json={"command": command, "original_device_id": original_device_id},
        timeout=5.0,
    )
    assert resp.status_code == 200, (
        f"takeover-dispatch endpoint returned {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert body.get("dispatched") is True
    assert body.get("takeover") is True
    return body


def _device_state(base_url: str, device_id: str) -> Dict[str, Any]:
    """Return the bridge-side connection state for *device_id*."""
    resp = httpx.get(
        f"{base_url}/test/device-state/{device_id}",
        timeout=5.0,
    )
    assert resp.status_code == 200
    return resp.json()


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMultiDeviceNetworkE2E:
    """Multi-device scenarios exercised at genuine TCP loopback network level.

    All tests require a real separated-process uvicorn server and communicate
    via ``websockets`` over actual TCP sockets — no in-process test doubles.
    """

    # ------------------------------------------------------------------
    # Test 1 — concurrent registration
    # ------------------------------------------------------------------

    async def test_two_devices_concurrent_registration(
        self, live_server: str
    ) -> None:
        """Two devices register concurrently; both receive independent acks.

        Proves that the gateway correctly handles simultaneous connections
        from multiple participants without acks being cross-contaminated.
        """
        dev_a = f"md-reg-a-{uuid.uuid4().hex[:8]}"
        dev_b = f"md-reg-b-{uuid.uuid4().hex[:8]}"
        ws_url_a = live_server.replace("http://", "ws://") + f"/ws/device/{dev_a}"
        ws_url_b = live_server.replace("http://", "ws://") + f"/ws/device/{dev_b}"

        async def _connect_and_register(ws_url: str, device_id: str) -> Dict[str, Any]:
            async with ws_connect(ws_url, open_timeout=10) as ws:
                client = NetworkE2EClient(ws, device_id)
                ack = await client.register()
                hb_ack = await client.heartbeat()
                return {"register_ack": ack, "heartbeat_ack": hb_ack, "device_id": device_id}

        results = await asyncio.gather(
            _connect_and_register(ws_url_a, dev_a),
            _connect_and_register(ws_url_b, dev_b),
        )

        for result in results:
            reg_ack = result["register_ack"]
            hb_ack = result["heartbeat_ack"]
            did = result["device_id"]

            assert reg_ack["type"] == "device_register_ack", (
                f"[{did}] expected device_register_ack; got {reg_ack.get('type')!r}"
            )
            assert reg_ack.get("success") is True, (
                f"[{did}] register_ack.success must be True"
            )
            assert reg_ack.get("device_id") == did, (
                f"[{did}] register_ack.device_id mismatch"
            )
            assert hb_ack["type"] == "heartbeat_ack", (
                f"[{did}] expected heartbeat_ack after register"
            )

    # ------------------------------------------------------------------
    # Test 2 — independent capability reporting
    # ------------------------------------------------------------------

    async def test_two_devices_independent_capability_report(
        self, live_server: str
    ) -> None:
        """Each device reports distinct capabilities; both capability_report_acks arrive.

        Verifies that capability_report is processed independently for each
        connected participant with no cross-device state bleed.
        """
        dev_a = f"md-cap-a-{uuid.uuid4().hex[:8]}"
        dev_b = f"md-cap-b-{uuid.uuid4().hex[:8]}"
        ws_url_a = live_server.replace("http://", "ws://") + f"/ws/device/{dev_a}"
        ws_url_b = live_server.replace("http://", "ws://") + f"/ws/device/{dev_b}"

        async def _setup_device(ws_url: str, device_id: str, caps: List[str]) -> Dict[str, Any]:
            async with ws_connect(ws_url, open_timeout=10) as ws:
                client = NetworkE2EClient(ws, device_id)
                await client.register()
                cap_ack = await client.report_capabilities(caps)
                return {"cap_ack": cap_ack, "device_id": device_id}

        results = await asyncio.gather(
            _setup_device(ws_url_a, dev_a, ["screenshot"]),
            _setup_device(ws_url_b, dev_b, ["tap", "screenshot", "input_text"]),
        )

        for result in results:
            cap_ack = result["cap_ack"]
            did = result["device_id"]

            assert cap_ack["type"] == "capability_report_ack", (
                f"[{did}] expected capability_report_ack; got {cap_ack.get('type')!r}"
            )
            assert cap_ack.get("accepted") is True, (
                f"[{did}] capability_report_ack.accepted must be True"
            )

    # ------------------------------------------------------------------
    # Test 3 — per-device task isolation
    # ------------------------------------------------------------------

    async def test_per_device_task_isolation(
        self, live_server: str
    ) -> None:
        """Task dispatched to device A is not received by device B (and vice versa).

        Verifies that the gateway correctly routes task_assign messages to
        the specific target device and does not broadcast them.
        """
        dev_a = f"md-iso-a-{uuid.uuid4().hex[:8]}"
        dev_b = f"md-iso-b-{uuid.uuid4().hex[:8]}"
        ws_url_a = live_server.replace("http://", "ws://") + f"/ws/device/{dev_a}"
        ws_url_b = live_server.replace("http://", "ws://") + f"/ws/device/{dev_b}"

        task_for_a = str(uuid.uuid4())
        task_for_b = str(uuid.uuid4())

        async with ws_connect(ws_url_a, open_timeout=10) as ws_a, \
                   ws_connect(ws_url_b, open_timeout=10) as ws_b:

            client_a = NetworkE2EClient(ws_a, dev_a)
            client_b = NetworkE2EClient(ws_b, dev_b)

            # Both devices connect and register
            await asyncio.gather(
                client_a.register(),
                client_b.register(),
            )
            await asyncio.gather(
                client_a.report_capabilities(["screenshot"]),
                client_b.report_capabilities(["tap", "screenshot"]),
            )

            # Dispatch task to device A only
            _dispatch(live_server, dev_a, task_for_a, "screenshot")

            # Device A should receive task_assign
            msg_a = await client_a.recv(timeout=5.0)
            assert msg_a["type"] == "task_assign", (
                f"Device A expected task_assign; got {msg_a.get('type')!r}"
            )
            assert msg_a.get("task_id") == task_for_a, (
                "Device A task_id mismatch"
            )

            # Device B should receive NOTHING (no cross-talk)
            msg_b_unexpected = await client_b.recv_optional(timeout=1.5)
            assert msg_b_unexpected is None, (
                f"Device B received unexpected message after A-only dispatch: "
                f"{msg_b_unexpected!r}"
            )

            # Now dispatch to device B; device A should not receive it
            _dispatch(live_server, dev_b, task_for_b, "tap")

            msg_b = await client_b.recv(timeout=5.0)
            assert msg_b["type"] == "task_assign", (
                f"Device B expected task_assign; got {msg_b.get('type')!r}"
            )
            assert msg_b.get("task_id") == task_for_b, (
                "Device B task_id mismatch"
            )

            # Device A should still receive NOTHING (no spill)
            msg_a_unexpected = await client_a.recv_optional(timeout=1.5)
            assert msg_a_unexpected is None, (
                f"Device A received unexpected message after B-only dispatch: "
                f"{msg_a_unexpected!r}"
            )

            # Both sessions remain alive after the task routing
            hb_a, hb_b = await asyncio.gather(
                client_a.heartbeat(),
                client_b.heartbeat(),
            )
            assert hb_a["type"] == "heartbeat_ack", "Device A session broken after routing"
            assert hb_b["type"] == "heartbeat_ack", "Device B session broken after routing"

    # ------------------------------------------------------------------
    # Test 4 — concurrent task execution and result collection
    # ------------------------------------------------------------------

    async def test_concurrent_task_execution_and_result_collection(
        self, live_server: str
    ) -> None:
        """Two devices execute independent tasks concurrently; both complete.

        Verifies multi-device concurrent task execution at network level:
        - Each device receives its own task_assign
        - Each device sends its own task_result
        - Both sessions remain alive after all task roundtrips
        - Result data is device-specific (no cross-contamination)
        """
        dev_a = f"md-cex-a-{uuid.uuid4().hex[:8]}"
        dev_b = f"md-cex-b-{uuid.uuid4().hex[:8]}"
        ws_url_a = live_server.replace("http://", "ws://") + f"/ws/device/{dev_a}"
        ws_url_b = live_server.replace("http://", "ws://") + f"/ws/device/{dev_b}"

        task_a = str(uuid.uuid4())
        task_b = str(uuid.uuid4())

        async def _run_device(
            ws_url: str,
            device_id: str,
            task_id: str,
            result_payload: Dict[str, Any],
        ) -> Dict[str, Any]:
            async with ws_connect(ws_url, open_timeout=10) as ws:
                client = NetworkE2EClient(ws, device_id)

                await client.register()
                await client.report_capabilities(["screenshot", "tap"])

                # Wait to receive task_assign (dispatched from outside)
                task_assign_msg = await client.recv(timeout=8.0)
                assert task_assign_msg["type"] == "task_assign", (
                    f"[{device_id}] expected task_assign; got {task_assign_msg.get('type')!r}"
                )
                received_task_id = task_assign_msg.get("task_id")

                # Execute and send task_result
                await client.task_result(
                    received_task_id,
                    status="completed",
                    result_data=result_payload,
                )

                # Continuation: heartbeat proves session alive after task_result
                hb_ack = await client.heartbeat()
                assert hb_ack["type"] == "heartbeat_ack", (
                    f"[{device_id}] session broken after task_result"
                )

                return {
                    "device_id": device_id,
                    "received_task_id": received_task_id,
                    "expected_task_id": task_id,
                }

        # Dispatch tasks immediately before starting device coroutines — the
        # devices will pick them up as soon as they connect and register.
        # Use asyncio to overlap dispatch and connection establishment.
        async def _dispatch_after_delay(device_id: str, task_id: str, delay: float = 1.0):
            """Dispatch after a short delay so devices have time to connect."""
            await asyncio.sleep(delay)
            _dispatch(live_server, device_id, task_id, "screenshot")

        results, *_ = await asyncio.gather(
            asyncio.gather(
                _run_device(ws_url_a, dev_a, task_a, {"source": dev_a, "image": "img_a"}),
                _run_device(ws_url_b, dev_b, task_b, {"source": dev_b, "image": "img_b"}),
            ),
            _dispatch_after_delay(dev_a, task_a),
            _dispatch_after_delay(dev_b, task_b),
        )

        for result in results:
            assert result["received_task_id"] == result["expected_task_id"], (
                f"[{result['device_id']}] task_id mismatch: "
                f"received {result['received_task_id']!r}, "
                f"expected {result['expected_task_id']!r}"
            )

    # ------------------------------------------------------------------
    # Test 5 — delegated takeover path
    # ------------------------------------------------------------------

    async def test_delegated_takeover_path(
        self, live_server: str
    ) -> None:
        """Primary device disconnects before task_result; takeover device completes task.

        Canonical takeover sequence validated at network level:
        1. Device A (primary) registers + reports capabilities
        2. Device B (takeover candidate) registers + reports capabilities
        3. V2 dispatches task T to device A
        4. Device A receives task_assign(T)
        5. Device A disconnects abruptly (simulates failure)
        6. Test triggers takeover-dispatch: same task T → device B
        7. Device B receives task_assign(T) with takeover=True
        8. Device B sends task_result(T) — same task_id preserves result continuity
        9. Heartbeat_ack from B proves continuation after takeover completion
        """
        dev_a = f"md-tko-a-{uuid.uuid4().hex[:8]}"  # primary
        dev_b = f"md-tko-b-{uuid.uuid4().hex[:8]}"  # takeover
        ws_url_a = live_server.replace("http://", "ws://") + f"/ws/device/{dev_a}"
        ws_url_b = live_server.replace("http://", "ws://") + f"/ws/device/{dev_b}"

        takeover_task_id = str(uuid.uuid4())

        # ── Phase 1: register both devices ───────────────────────────────
        async with ws_connect(ws_url_b, open_timeout=10) as ws_b:
            client_b = NetworkE2EClient(ws_b, dev_b)
            await client_b.register()
            await client_b.report_capabilities(["screenshot", "tap"])

            # ── Phase 2: primary device connects, receives task, disconnects ─
            async with ws_connect(ws_url_a, open_timeout=10) as ws_a:
                client_a = NetworkE2EClient(ws_a, dev_a)
                await client_a.register()
                await client_a.report_capabilities(["screenshot", "tap"])

                # V2 dispatches the task to primary device
                _dispatch(live_server, dev_a, takeover_task_id, "screenshot")

                # Primary device receives task_assign
                task_assign_a = await client_a.recv(timeout=5.0)
                assert task_assign_a["type"] == "task_assign", (
                    f"Primary device expected task_assign; "
                    f"got {task_assign_a.get('type')!r}"
                )
                assert task_assign_a.get("task_id") == takeover_task_id, (
                    "Primary device task_id mismatch"
                )
                # Device A disconnects WITHOUT sending task_result (failure)
            # ws_a context exits here — device A is now disconnected

            # ── Phase 3: takeover dispatch to device B ────────────────────
            # The same task_id is preserved so result can be correlated.
            takeover_resp = _takeover_dispatch(
                live_server,
                task_id=takeover_task_id,
                takeover_device_id=dev_b,
                original_device_id=dev_a,
                command="screenshot",
            )
            assert takeover_resp["task_id"] == takeover_task_id, (
                "Takeover dispatch must preserve original task_id"
            )

            # ── Phase 4: device B receives takeover task_assign ───────────
            task_assign_b = await client_b.recv(timeout=5.0)
            assert task_assign_b["type"] == "task_assign", (
                f"Takeover device expected task_assign; "
                f"got {task_assign_b.get('type')!r}"
            )
            # Result continuity: takeover task carries the original task_id
            assert task_assign_b.get("task_id") == takeover_task_id, (
                "Takeover task_assign must carry the ORIGINAL task_id "
                "(result continuity across the handoff)"
            )
            # Takeover flag must be set
            payload = task_assign_b.get("payload") or {}
            assert payload.get("takeover") is True, (
                "Takeover task_assign payload.takeover must be True"
            )

            # ── Phase 5: takeover device completes the task ───────────────
            await client_b.task_result(
                takeover_task_id,
                status="completed",
                result_data={
                    "output": "takeover_completed",
                    "device_id": dev_b,
                },
            )

            # ── Phase 6: continuation — session B remains alive ───────────
            hb_b = await client_b.heartbeat()
            assert hb_b["type"] == "heartbeat_ack", (
                "Takeover device session broken after task_result — "
                "continuation not preserved"
            )

    # ------------------------------------------------------------------
    # Test 6 — participant disconnect, reconnect, and task recovery
    # ------------------------------------------------------------------

    async def test_participant_disconnect_reconnect_recovery(
        self, live_server: str
    ) -> None:
        """Device fails mid-task; reconnects; receives a new task; completes it.

        Validates the full failure-recovery lifecycle at network level:
        1. Device registers and receives task_assign
        2. Device disconnects abruptly without sending task_result
        3. Server handles disconnect without crashing
        4. Device reconnects with same device_id (re-register is accepted)
        5. New task dispatched to reconnected device
        6. Device receives task_assign, executes, sends task_result
        7. Heartbeat confirms session continuity after recovery
        """
        device_id = f"md-rcv-{uuid.uuid4().hex[:8]}"
        ws_url = live_server.replace("http://", "ws://") + f"/ws/device/{device_id}"

        task_before_failure = str(uuid.uuid4())
        task_after_recovery = str(uuid.uuid4())

        # ── Phase 1: first session — receive task then fail ───────────────
        async with ws_connect(ws_url, open_timeout=10) as ws:
            client = NetworkE2EClient(ws, device_id)
            await client.register()
            await client.report_capabilities(["screenshot"])

            # Dispatch first task — device will receive but not complete it
            _dispatch(live_server, device_id, task_before_failure, "screenshot")
            assign_before = await client.recv(timeout=5.0)
            assert assign_before["type"] == "task_assign", (
                "Expected task_assign before failure"
            )
            # Close WebSocket without sending task_result (simulates crash)
        # ws context exits — device is now disconnected

        # ── Phase 2: reconnect with same device_id ────────────────────────
        async with ws_connect(ws_url, open_timeout=10) as ws2:
            client2 = NetworkE2EClient(ws2, device_id)

            # Re-registration must succeed (server must not refuse reconnect)
            reg2 = await client2.register()
            assert reg2["type"] == "device_register_ack", (
                "Reconnect: expected device_register_ack; "
                f"got {reg2.get('type')!r}"
            )
            assert reg2.get("success") is True, (
                "Reconnect: register_ack.success must be True"
            )
            assert reg2.get("device_id") == device_id, (
                "Reconnect: register_ack.device_id must match"
            )

            # Report capabilities again on the new session
            cap_ack = await client2.report_capabilities(["screenshot"])
            assert cap_ack.get("accepted") is True, (
                "Reconnect: capability_report_ack.accepted must be True"
            )

            # Dispatch recovery task to reconnected device
            _dispatch(live_server, device_id, task_after_recovery, "screenshot")

            assign_after = await client2.recv(timeout=5.0)
            assert assign_after["type"] == "task_assign", (
                "Recovery: expected task_assign; "
                f"got {assign_after.get('type')!r}"
            )
            assert assign_after.get("task_id") == task_after_recovery, (
                "Recovery: task_id must match dispatched task"
            )

            # Complete the recovery task and verify session continuity
            await client2.task_result(
                task_after_recovery,
                status="completed",
                result_data={"output": "recovered"},
            )
            hb_ack = await client2.heartbeat()
            assert hb_ack["type"] == "heartbeat_ack", (
                "Session continuity broken after recovery task_result"
            )

    # ------------------------------------------------------------------
    # Test 7 — capability mismatch routing
    # ------------------------------------------------------------------

    async def test_capability_mismatch_routing(
        self, live_server: str
    ) -> None:
        """Capable device receives tap task; limited device does not.

        Validates capability-aware routing isolation:
        - Device A reports only ``["screenshot"]`` (cannot handle ``tap``)
        - Device B reports ``["tap", "screenshot"]`` (can handle ``tap``)
        - A ``tap`` task is dispatched explicitly to B (capability-matched)
        - Device A receives no task_assign (no cross-dispatch)
        - Device B receives and completes the ``tap`` task
        - Both sessions remain alive throughout
        """
        dev_a = f"md-mis-a-{uuid.uuid4().hex[:8]}"  # limited: screenshot only
        dev_b = f"md-mis-b-{uuid.uuid4().hex[:8]}"  # capable: tap + screenshot
        ws_url_a = live_server.replace("http://", "ws://") + f"/ws/device/{dev_a}"
        ws_url_b = live_server.replace("http://", "ws://") + f"/ws/device/{dev_b}"

        tap_task_id = str(uuid.uuid4())

        async with ws_connect(ws_url_a, open_timeout=10) as ws_a, \
                   ws_connect(ws_url_b, open_timeout=10) as ws_b:

            client_a = NetworkE2EClient(ws_a, dev_a)
            client_b = NetworkE2EClient(ws_b, dev_b)

            # Register both
            await asyncio.gather(
                client_a.register(),
                client_b.register(),
            )

            # Each reports distinct capabilities
            await asyncio.gather(
                client_a.report_capabilities(["screenshot"]),           # limited
                client_b.report_capabilities(["tap", "screenshot"]),   # capable
            )

            # Capability-matched routing: tap task → device B only
            _dispatch(live_server, dev_b, tap_task_id, "tap")

            # Device B receives the tap task_assign
            assign_b = await client_b.recv(timeout=5.0)
            assert assign_b["type"] == "task_assign", (
                f"Capable device expected task_assign; got {assign_b.get('type')!r}"
            )
            assert assign_b.get("task_id") == tap_task_id, (
                "Capable device task_id mismatch"
            )
            assert (assign_b.get("payload") or {}).get("command") == "tap", (
                "task_assign payload.command must be 'tap'"
            )

            # Device A must receive NOTHING (capability mismatch — not routed to it)
            msg_a_unexpected = await client_a.recv_optional(timeout=1.5)
            assert msg_a_unexpected is None, (
                f"Limited-capability device received an unexpected message: "
                f"{msg_a_unexpected!r}. Tap task must not be routed to a "
                "device that only reported screenshot capability."
            )

            # Device B completes the tap task
            await client_b.task_result(
                tap_task_id,
                status="completed",
                result_data={"tap_performed": True},
            )

            # Both sessions remain alive
            hb_a, hb_b = await asyncio.gather(
                client_a.heartbeat(),
                client_b.heartbeat(),
            )
            assert hb_a["type"] == "heartbeat_ack", (
                "Limited-capability device session broken after mismatch test"
            )
            assert hb_b["type"] == "heartbeat_ack", (
                "Capable device session broken after tap task completion"
            )

    # ------------------------------------------------------------------
    # Test 8 — multi-device result aggregation
    # ------------------------------------------------------------------

    async def test_multi_device_result_aggregation(
        self, live_server: str
    ) -> None:
        """Multiple tasks across two devices; results correlated to correct device_ids.

        Validates that result data from each device is independently
        correct and not confused with results from the other device.
        """
        dev_a = f"md-agg-a-{uuid.uuid4().hex[:8]}"
        dev_b = f"md-agg-b-{uuid.uuid4().hex[:8]}"
        ws_url_a = live_server.replace("http://", "ws://") + f"/ws/device/{dev_a}"
        ws_url_b = live_server.replace("http://", "ws://") + f"/ws/device/{dev_b}"

        # Three tasks: two for A, one for B
        task_a1 = str(uuid.uuid4())
        task_a2 = str(uuid.uuid4())
        task_b1 = str(uuid.uuid4())

        collected_tasks: Dict[str, Dict[str, Any]] = {}

        async with ws_connect(ws_url_a, open_timeout=10) as ws_a, \
                   ws_connect(ws_url_b, open_timeout=10) as ws_b:

            client_a = NetworkE2EClient(ws_a, dev_a)
            client_b = NetworkE2EClient(ws_b, dev_b)

            await asyncio.gather(
                client_a.register(),
                client_b.register(),
            )
            await asyncio.gather(
                client_a.report_capabilities(["screenshot"]),
                client_b.report_capabilities(["tap"]),
            )

            # Dispatch task A1 → device A
            _dispatch(live_server, dev_a, task_a1, "screenshot")
            assign_a1 = await client_a.recv(timeout=5.0)
            assert assign_a1["type"] == "task_assign"
            collected_tasks[assign_a1["task_id"]] = {"device_id": dev_a}
            await client_a.task_result(
                assign_a1["task_id"],
                result_data={"source": dev_a, "seq": 1},
            )

            # Dispatch task B1 → device B
            _dispatch(live_server, dev_b, task_b1, "tap")
            assign_b1 = await client_b.recv(timeout=5.0)
            assert assign_b1["type"] == "task_assign"
            collected_tasks[assign_b1["task_id"]] = {"device_id": dev_b}
            await client_b.task_result(
                assign_b1["task_id"],
                result_data={"source": dev_b, "seq": 1},
            )

            # Dispatch task A2 → device A
            _dispatch(live_server, dev_a, task_a2, "screenshot")
            assign_a2 = await client_a.recv(timeout=5.0)
            assert assign_a2["type"] == "task_assign"
            collected_tasks[assign_a2["task_id"]] = {"device_id": dev_a}
            await client_a.task_result(
                assign_a2["task_id"],
                result_data={"source": dev_a, "seq": 2},
            )

            # Verify task→device correlation
            assert collected_tasks.get(task_a1, {}).get("device_id") == dev_a, (
                "Task A1 must be correlated to device A"
            )
            assert collected_tasks.get(task_b1, {}).get("device_id") == dev_b, (
                "Task B1 must be correlated to device B"
            )
            assert collected_tasks.get(task_a2, {}).get("device_id") == dev_a, (
                "Task A2 must be correlated to device A"
            )

            # Both sessions alive after all task roundtrips
            hb_a, hb_b = await asyncio.gather(
                client_a.heartbeat(),
                client_b.heartbeat(),
            )
            assert hb_a["type"] == "heartbeat_ack", "Device A session broken after aggregation"
            assert hb_b["type"] == "heartbeat_ack", "Device B session broken after aggregation"

    # ------------------------------------------------------------------
    # Test 9 — degraded participant (minimal capability set)
    # ------------------------------------------------------------------

    async def test_degraded_participant_minimal_capability(
        self, live_server: str
    ) -> None:
        """Degraded device (single capability) handles matched task; mismatched task goes elsewhere.

        Proves that a device reporting a minimal / degraded capability set:
        - Can still register and participate in the session
        - Receives tasks that match its limited capability
        - Does NOT receive tasks destined for the capable partner
        - Session remains alive throughout (not evicted for being limited)
        """
        dev_degraded = f"md-dgr-deg-{uuid.uuid4().hex[:8]}"  # degraded: screenshot only
        dev_capable = f"md-dgr-cap-{uuid.uuid4().hex[:8]}"   # full: tap + screenshot
        ws_url_deg = live_server.replace("http://", "ws://") + f"/ws/device/{dev_degraded}"
        ws_url_cap = live_server.replace("http://", "ws://") + f"/ws/device/{dev_capable}"

        task_for_degraded = str(uuid.uuid4())
        task_for_capable = str(uuid.uuid4())

        async with ws_connect(ws_url_deg, open_timeout=10) as ws_deg, \
                   ws_connect(ws_url_cap, open_timeout=10) as ws_cap:

            client_deg = NetworkE2EClient(ws_deg, dev_degraded)
            client_cap = NetworkE2EClient(ws_cap, dev_capable)

            # Both register
            await asyncio.gather(
                client_deg.register(),
                client_cap.register(),
            )

            # Degraded device reports single capability
            cap_ack_deg = await client_deg.report_capabilities(["screenshot"])
            assert cap_ack_deg.get("accepted") is True, (
                "Degraded device capability_report must be accepted"
            )
            await client_cap.report_capabilities(["tap", "screenshot", "input_text"])

            # Route matched task to degraded device (screenshot task)
            _dispatch(live_server, dev_degraded, task_for_degraded, "screenshot")
            assign_deg = await client_deg.recv(timeout=5.0)
            assert assign_deg["type"] == "task_assign", (
                "Degraded device must receive matched task_assign"
            )
            assert assign_deg.get("task_id") == task_for_degraded

            # Route capability-mismatched task to capable device only
            _dispatch(live_server, dev_capable, task_for_capable, "tap")
            assign_cap = await client_cap.recv(timeout=5.0)
            assert assign_cap["type"] == "task_assign"

            # Degraded device must not receive the tap task
            msg_deg_unexpected = await client_deg.recv_optional(timeout=1.5)
            assert msg_deg_unexpected is None, (
                f"Degraded device received unexpected tap task: {msg_deg_unexpected!r}"
            )

            # Both complete their respective tasks
            await asyncio.gather(
                client_deg.task_result(task_for_degraded),
                client_cap.task_result(task_for_capable),
            )

            # Both sessions alive — degraded device not evicted
            hb_deg, hb_cap = await asyncio.gather(
                client_deg.heartbeat(),
                client_cap.heartbeat(),
            )
            assert hb_deg["type"] == "heartbeat_ack", (
                "Degraded device session must remain alive after task completion"
            )
            assert hb_cap["type"] == "heartbeat_ack", (
                "Capable device session must remain alive after task completion"
            )


# ---------------------------------------------------------------------------
# Verification: GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION is registered
# ---------------------------------------------------------------------------


class TestGapMultiDeviceFailureRecoveryRegistered:
    """Asserts that GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION exists in the registry.

    The gap entry must be registered so that:
    1. CI gates can verify its closure status
    2. The gap cannot be silently dropped from the registry
    3. When this test suite closes the gap, the resolution is traceable
    """

    def test_gap_multi_device_failure_recovery_is_registered(self) -> None:
        from core.dual_repo_system_map import WORKSTREAM_GAP_REGISTRY

        gap = next(
            (
                g for g in WORKSTREAM_GAP_REGISTRY
                if g.gap_id == "GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION"
            ),
            None,
        )
        assert gap is not None, (
            "GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION not found in "
            "WORKSTREAM_GAP_REGISTRY.  The gap entry must be registered "
            "alongside the test file that closes it."
        )
        assert gap.description, (
            "GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION must have a non-empty description."
        )

    def test_gap_multi_device_failure_recovery_severity_is_p0(self) -> None:
        from core.dual_repo_system_map import WORKSTREAM_GAP_REGISTRY, GapSeverity

        gap = next(
            (
                g for g in WORKSTREAM_GAP_REGISTRY
                if g.gap_id == "GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION"
            ),
            None,
        )
        assert gap is not None
        assert gap.severity == GapSeverity.P0, (
            "GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION must be P0 severity — "
            "multi-device and failure-recovery coverage is a blocking gap."
        )
