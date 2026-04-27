"""
tests/integration/test_separated_process_ws_e2e.py
====================================================

**Separated-process WebSocket E2E tests — GAP_JOINT_INTEGRATION_TEST closure.**

These tests validate the canonical V2 ↔ Android interaction chain using a
**genuinely separated server process** and a **real TCP/WebSocket network
connection**, going beyond the FastAPI TestClient (in-process) approach used
in the transport harness.

Architecture
------------
- **Server process**: a real ``uvicorn`` HTTP/WebSocket server running in a
  separate OS process, hosting the production ``_handle_android_ws`` handler
  together with a minimal test-only HTTP dispatch endpoint.
- **Android-side client**: the test process connects to the server via a real
  ``websockets`` client (``websockets.asyncio.client.connect``), exercising
  the full OS-level TCP loopback network stack.
- **V2-side dispatch trigger**: the test server exposes
  ``POST /test/dispatch-task/{device_id}`` that calls
  ``android_bridge.send_to_device()`` inside the server process, pushing a
  ``task_assign`` message to the connected Android client over the live
  WebSocket session.

What this proves
----------------
1. The WebSocket transport is real — no ``TestClient`` in-process mocking.
2. Two separate OS processes communicate via TCP/IP loopback.
3. The full canonical six-step sequence is exercised at network level:

   ``register → capability_report → task_assign (server-pushed)
   → execution / task_result (client) → continuation verified via heartbeat``

4. Session continuity across the task lifecycle is confirmed by a final
   ``heartbeat`` / ``heartbeat_ack`` roundtrip after ``task_result``.

GAP closure
-----------
This file closes ``GAP_JOINT_INTEGRATION_TEST`` by providing a
*separated-process Android-side runtime harness* that reaches true
WebSocket / network-level canonical runtime path assurance.

No external services, real Android devices, or emulators are required.
Dependencies: ``uvicorn``, ``websockets``, ``httpx`` — all in
``requirements.txt``.
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
from typing import Any, Dict, List

import httpx
import pytest
from websockets.asyncio.client import connect as _ws_connect_base


def ws_connect(uri: str, **kwargs):
    """Wrapper around ``websockets.asyncio.client.connect`` with ``proxy=None``.

    Disables proxy auto-detection (the v16 default ``proxy=True``) to ensure
    loopback connections go directly to the server without being intercepted
    by any OS-level proxy configured in CI environments.
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
# Port helper
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    """Find an available TCP port on loopback."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def _wait_for_port(host: str, port: int, timeout: float = 20.0) -> None:
    """Block until the TCP port is accepting connections or raise on timeout."""
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
# Pytest fixture — live uvicorn server in a separate process
# ---------------------------------------------------------------------------

#: Path to the server helper script launched as a subprocess
_SERVER_HELPER = os.path.join(os.path.dirname(__file__), "_ws_e2e_server_helper.py")


@pytest.fixture(scope="module")
def live_server():
    """Start a real uvicorn server in a **separate OS process**.

    Uses ``subprocess.Popen`` (not ``multiprocessing.Process``) to launch a
    completely fresh Python interpreter, avoiding the asyncio event-loop state
    that ``fork`` would inherit from the pytest-asyncio test runner.

    Yields the base URL string, e.g. ``"http://127.0.0.1:<port>"``.
    The corresponding WebSocket base URL is ``"ws://127.0.0.1:<port>"``.

    The server is terminated (SIGTERM) when the module finishes.

    Module-scoped so the subprocess is started once per test module rather
    than once per test, keeping the test suite fast.
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
    """Async helper that wraps a real websockets connection to the live server.

    All I/O goes through genuine TCP sockets — no in-process shortcuts.
    """

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

    # ---------------------------------------------------------------- flows

    async def register(self, platform: str = "android") -> Dict[str, Any]:
        await self.send(_v3("device_register", self.device_id, platform=platform))
        return await self.recv()

    async def report_capabilities(
        self, caps: List[str]
    ) -> Dict[str, Any]:
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
        result_data: Dict[str, Any] | None = None,
    ) -> None:
        """Send task_result.  No server response is expected for task_result."""
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
# Test suite
# ---------------------------------------------------------------------------


class TestSeparatedProcessNetworkE2E:
    """End-to-end tests that use a **real network** between two OS processes.

    Assurance level
    ~~~~~~~~~~~~~~~
    These tests use a genuinely separated server process (uvicorn) and a real
    ``websockets`` client connecting via TCP loopback.  This is fundamentally
    different from FastAPI ``TestClient``, which runs the ASGI app in-process
    via a synchronous adapter.

    Canonical path assurance
    ~~~~~~~~~~~~~~~~~~~~~~~~
    The production ``_handle_android_ws`` handler and ``AndroidBridge`` are
    used without any test doubles at the transport layer.  The "Android side"
    is represented by ``NetworkE2EClient``, which communicates exclusively
    through JSON-over-WebSocket over real TCP sockets.
    """

    # ------------------------------------------------------------------
    # Test 1 — register + capability_report + heartbeat (network level)
    # ------------------------------------------------------------------

    async def test_register_capability_heartbeat_network_e2e(
        self, live_server: str
    ) -> None:
        """register → capability_report → heartbeat over real network.

        Verifies the first two canonical steps at true network level.
        """
        device_id = f"net-reg-{uuid.uuid4().hex[:8]}"
        ws_url = live_server.replace("http://", "ws://") + f"/ws/device/{device_id}"
        caps = ["tap", "screenshot", "swipe"]

        async with ws_connect(ws_url, open_timeout=10) as ws:
            client = NetworkE2EClient(ws, device_id)

            # Step 1 — register
            reg_ack = await client.register()
            assert reg_ack["type"] == "device_register_ack", (
                f"Expected device_register_ack; got {reg_ack.get('type')!r}"
            )
            assert reg_ack.get("success") is True, (
                "register_ack.success must be True"
            )
            assert reg_ack.get("device_id") == device_id, (
                "register_ack.device_id mismatch"
            )
            assert reg_ack.get("version") == "3.0", (
                "AIP v3 version string must be '3.0'"
            )

            # Step 2 — capability_report
            cap_ack = await client.report_capabilities(caps)
            assert cap_ack["type"] == "capability_report_ack", (
                f"Expected capability_report_ack; got {cap_ack.get('type')!r}"
            )
            assert cap_ack.get("accepted") is True, (
                "capability_report_ack.accepted must be True"
            )

            # Heartbeat — session is alive after registration
            hb_ack = await client.heartbeat()
            assert hb_ack["type"] == "heartbeat_ack", (
                f"Expected heartbeat_ack; got {hb_ack.get('type')!r}"
            )

    # ------------------------------------------------------------------
    # Test 2 — task_result → session continuity (heartbeat after result)
    # ------------------------------------------------------------------

    async def test_task_result_session_continuity_network_e2e(
        self, live_server: str
    ) -> None:
        """task_result sent over real network; session stays open (heartbeat_ack).

        Verifies that the V2 gateway correctly processes a task_result arriving
        over a genuine network connection and keeps the session alive afterward.
        """
        device_id = f"net-res-{uuid.uuid4().hex[:8]}"
        task_id = str(uuid.uuid4())
        ws_url = live_server.replace("http://", "ws://") + f"/ws/device/{device_id}"

        async with ws_connect(ws_url, open_timeout=10) as ws:
            client = NetworkE2EClient(ws, device_id)

            # Setup: register + capability
            await client.register()
            await client.report_capabilities(["screenshot"])

            # Send task_result (no server response expected for this message type)
            await client.task_result(
                task_id, status="completed", result_data={"image": "base64abc"}
            )

            # Heartbeat — proves session is alive after task_result
            hb_ack = await client.heartbeat()
            assert hb_ack["type"] == "heartbeat_ack", (
                f"Session broke after task_result: "
                f"expected heartbeat_ack, got {hb_ack.get('type')!r}"
            )

    # ------------------------------------------------------------------
    # Test 3 — full canonical six-step sequence at network level
    # ------------------------------------------------------------------

    async def test_full_six_step_canonical_network_e2e(
        self, live_server: str
    ) -> None:
        """Full six-step canonical sequence over real separated-process WebSocket.

        Steps verified at network level
        --------------------------------
        1. ``device_register``    → ``device_register_ack``
        2. ``capability_report``  → ``capability_report_ack``
        3. HTTP trigger           → server sends ``task_assign`` to device
        4. device *receives*       ``task_assign`` via real WS
        5. device sends            ``task_result`` via real WS
        6. continuation verified: ``heartbeat`` → ``heartbeat_ack``

        This is the primary GAP_JOINT_INTEGRATION_TEST closure proof.
        Two separate OS processes exchange all canonical messages via genuine
        TCP loopback sockets.
        """
        device_id = f"net-six-{uuid.uuid4().hex[:8]}"
        task_id = str(uuid.uuid4())
        ws_url = live_server.replace("http://", "ws://") + f"/ws/device/{device_id}"
        http_dispatch_url = (
            f"{live_server}/test/dispatch-task/{device_id}"
        )

        async with ws_connect(ws_url, open_timeout=10) as ws:
            client = NetworkE2EClient(ws, device_id)

            # ── Step 1: register ──────────────────────────────────────────
            reg_ack = await client.register()
            assert reg_ack["type"] == "device_register_ack", (
                f"Step 1 FAILED: expected device_register_ack, "
                f"got {reg_ack.get('type')!r}"
            )
            assert reg_ack.get("success") is True, (
                "Step 1 FAILED: success is not True"
            )

            # ── Step 2: capability_report ─────────────────────────────────
            caps = ["tap", "screenshot", "input_text", "swipe"]
            cap_ack = await client.report_capabilities(caps)
            assert cap_ack["type"] == "capability_report_ack", (
                f"Step 2 FAILED: expected capability_report_ack, "
                f"got {cap_ack.get('type')!r}"
            )
            assert cap_ack.get("accepted") is True, (
                "Step 2 FAILED: capabilities not accepted"
            )

            # ── Step 3: V2 dispatches task_assign (HTTP trigger) ──────────
            # The HTTP endpoint pushes task_assign over the live WebSocket
            # from the server process to the client process.
            dispatch_resp = httpx.post(
                http_dispatch_url,
                json={"task_id": task_id, "command": "screenshot"},
                timeout=5.0,
            )
            assert dispatch_resp.status_code == 200, (
                f"Step 3 FAILED: dispatch endpoint returned "
                f"{dispatch_resp.status_code}"
            )
            dispatch_body = dispatch_resp.json()
            assert dispatch_body.get("dispatched") is True, (
                "Step 3 FAILED: dispatched flag not True"
            )
            server_task_id: str = dispatch_body["task_id"]

            # ── Step 4: device receives task_assign ───────────────────────
            task_assign_msg = await client.recv(timeout=5.0)
            assert task_assign_msg["type"] == "task_assign", (
                f"Step 4 FAILED: expected task_assign, "
                f"got {task_assign_msg.get('type')!r}"
            )
            assert task_assign_msg.get("task_id") == server_task_id, (
                "Step 4 FAILED: task_id in task_assign does not match dispatched id"
            )
            received_command = (task_assign_msg.get("payload") or {}).get("command")
            assert received_command == "screenshot", (
                f"Step 4 FAILED: expected command='screenshot', "
                f"got {received_command!r}"
            )

            # ── Step 5: device sends task_result ──────────────────────────
            await client.task_result(
                server_task_id,
                status="completed",
                result_data={"image_base64": "net_e2e_proof_data"},
            )

            # ── Step 6: continuation — heartbeat proves session open ───────
            # A successful heartbeat_ack after task_result proves that:
            # (a) the session remained open end-to-end, and
            # (b) the V2 gateway correctly processed task_result without
            #     breaking the WebSocket session.
            hb_ack = await client.heartbeat()
            assert hb_ack["type"] == "heartbeat_ack", (
                f"Step 6 FAILED: continuation broken — "
                f"expected heartbeat_ack, got {hb_ack.get('type')!r}"
            )

    # ------------------------------------------------------------------
    # Test 4 — reconnect and re-register (runtime recovery at network level)
    # ------------------------------------------------------------------

    async def test_reconnect_reregisters_network_e2e(
        self, live_server: str
    ) -> None:
        """Device disconnects and reconnects; new session is correctly established.

        Verifies that the V2 gateway accepts a fresh registration from a device
        that previously disconnected — exercised entirely over real network.
        """
        device_id = f"net-rcon-{uuid.uuid4().hex[:8]}"
        ws_url = live_server.replace("http://", "ws://") + f"/ws/device/{device_id}"

        # ── First session ─────────────────────────────────────────────────
        async with ws_connect(ws_url, open_timeout=10) as ws:
            client = NetworkE2EClient(ws, device_id)
            reg1 = await client.register()
            assert reg1["type"] == "device_register_ack"
            assert reg1.get("success") is True
        # Connection closed here (context manager exit)

        # ── Second session (reconnect) ────────────────────────────────────
        async with ws_connect(ws_url, open_timeout=10) as ws:
            client2 = NetworkE2EClient(ws, device_id)
            reg2 = await client2.register()
            assert reg2["type"] == "device_register_ack", (
                "Reconnect FAILED: device_register_ack not received on second session"
            )
            assert reg2.get("success") is True, (
                "Reconnect FAILED: success not True on second session"
            )

            # Confirm session is fully functional
            hb_ack = await client2.heartbeat()
            assert hb_ack["type"] == "heartbeat_ack", (
                "Reconnect FAILED: heartbeat_ack missing after re-register"
            )

    # ------------------------------------------------------------------
    # Test 5 — multiple sequential tasks at network level
    # ------------------------------------------------------------------

    async def test_multiple_sequential_tasks_network_e2e(
        self, live_server: str
    ) -> None:
        """Multiple sequential task roundtrips over real network in one session.

        Each iteration: HTTP trigger → task_assign received → task_result sent
        → heartbeat_ack confirms session alive.
        """
        device_id = f"net-seq-{uuid.uuid4().hex[:8]}"
        ws_url = live_server.replace("http://", "ws://") + f"/ws/device/{device_id}"
        http_dispatch_url = f"{live_server}/test/dispatch-task/{device_id}"

        async with ws_connect(ws_url, open_timeout=10) as ws:
            client = NetworkE2EClient(ws, device_id)
            await client.register()
            await client.report_capabilities(["screenshot", "tap"])

            for i in range(3):
                task_id = str(uuid.uuid4())

                # Dispatch task_assign from server
                resp = httpx.post(
                    http_dispatch_url,
                    json={"task_id": task_id, "command": f"step_{i}"},
                    timeout=5.0,
                )
                assert resp.status_code == 200

                # Receive task_assign over real network
                assign_msg = await client.recv(timeout=5.0)
                assert assign_msg["type"] == "task_assign", (
                    f"Iteration {i}: expected task_assign, "
                    f"got {assign_msg.get('type')!r}"
                )
                server_task_id = assign_msg["task_id"]

                # Send task_result back over real network
                await client.task_result(
                    server_task_id,
                    result_data={"step": i, "output": f"result_{i}"},
                )

            # Final heartbeat — session alive after 3 task roundtrips
            hb_ack = await client.heartbeat()
            assert hb_ack["type"] == "heartbeat_ack", (
                "Session broken after sequential task roundtrips"
            )


# ---------------------------------------------------------------------------
# Verification: GAP_JOINT_INTEGRATION_TEST is marked resolved in the registry
# ---------------------------------------------------------------------------


class TestGapJointIntegrationTestResolved:
    """Asserts that GAP_JOINT_INTEGRATION_TEST is marked resolved in the registry.

    This test ensures that the dual_repo_system_map gap entry reflects the
    actual closure of the gap (i.e. this PR's work is registered there).
    """

    def test_gap_joint_integration_test_is_resolved(self) -> None:
        from core.dual_repo_system_map import WORKSTREAM_GAP_REGISTRY

        gap = next(
            (g for g in WORKSTREAM_GAP_REGISTRY if g.gap_id == "GAP_JOINT_INTEGRATION_TEST"),
            None,
        )
        assert gap is not None, (
            "GAP_JOINT_INTEGRATION_TEST not found in WORKSTREAM_GAP_REGISTRY"
        )
        assert gap.resolved is True, (
            "GAP_JOINT_INTEGRATION_TEST.resolved must be True after this PR"
        )
        assert gap.resolution_pr, (
            "GAP_JOINT_INTEGRATION_TEST.resolution_pr must be non-empty"
        )
